"""Discover saved workflow candidates; graph inspection remains authoritative."""
import json
import re
import threading
from .atomic_files import atomic_json
from datetime import datetime, timezone
from pathlib import Path

_cache_lock = threading.Lock()


def _conversion_cache(settings):
    try:
        value = json.loads((settings.data_dir / "workflow-conversion-status.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def record_conversion(settings, workflow_id, successful, error=None):
    resolved = workflow_source_path(settings, workflow_id)
    if resolved is None:
        return
    root, path = resolved
    stat = path.stat()
    with _cache_lock:
        cache = _conversion_cache(settings)
        prefix = "defaults/" if getattr(settings, "comfy_workflow_defaults_root", None) and root == settings.comfy_workflow_defaults_root.resolve() else "custom/"
        key = prefix + path.relative_to(root.resolve()).as_posix()
        cache[key] = {**cache.get(key, {}), "mtime_ns": stat.st_mtime_ns, "size": stat.st_size,
                      "successful": successful, "last_conversion_at": datetime.now(timezone.utc).isoformat(),
                      "conversion_retryable": any(word in str(error).lower() for word in ("timeout", "timed out", "connection", "object_info", "structured envelope", "unavailable")),
                      "last_conversion_error": str(error)[:500] if error else None}
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(settings.data_dir / "workflow-conversion-status.json", cache)


def record_execution(settings, workflow_id, successful, error=None):
    """Remember render evidence for the immutable source workflow."""
    resolved = workflow_source_path(settings, workflow_id)
    if resolved is None:
        return
    root, path = resolved
    stat = path.stat()
    prefix = "defaults/" if getattr(settings, "comfy_workflow_defaults_root", None) and root == settings.comfy_workflow_defaults_root.resolve() else "custom/"
    key = prefix + path.relative_to(root.resolve()).as_posix()
    with _cache_lock:
        cache = _conversion_cache(settings)
        previous = cache.get(key, {})
        cache[key] = {**previous, "mtime_ns": stat.st_mtime_ns, "size": stat.st_size,
                      "render_success_count": int(previous.get("render_success_count", 0)) + int(successful),
                      "render_failure_count": int(previous.get("render_failure_count", 0)) + int(not successful),
                      "last_render_status": "completed" if successful else "failed",
                      "last_render_at": datetime.now(timezone.utc).isoformat(),
                      "last_render_error": None if successful else str(error or "Render failed")[:500]}
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(settings.data_dir / "workflow-conversion-status.json", cache)


def workflow_source_path(settings, workflow_id):
    """Resolve a discovered workflow, preferring the managed Darius defaults."""
    path_value = Path(workflow_id)
    if path_value.is_absolute() or ".." in path_value.parts or ":" in workflow_id or "\\" in workflow_id:
        return None
    roots = []
    defaults = getattr(settings, "comfy_workflow_defaults_root", None)
    if defaults is not None:
        roots.append(defaults)
    if settings.comfy_workflow_root is not None:
        roots.append(settings.comfy_workflow_root)
    for root in roots:
        root = root.resolve()
        path = (root / path_value).resolve()
        if path.is_relative_to(root) and path.is_file():
            return root, path
    return None


def discover_workflows(settings, query="", output_kind="video", source_kind="image", limit=30, *, defaults_only=True):
    roots = []
    defaults = getattr(settings, "comfy_workflow_defaults_root", None)
    if defaults is not None and defaults.is_dir():
        roots.append((defaults, True))
    if not defaults_only and settings.comfy_workflow_root is not None and settings.comfy_workflow_root.is_dir():
        roots.append((settings.comfy_workflow_root, False))
    if not roots:
        return {"workflows": [], "error": "Saved ComfyUI workflow directory is not configured"}
    words = set(re.findall(r"[a-z0-9]+", str(query).lower()))
    conversion_cache = _conversion_cache(settings)
    candidates = []
    seen_ids = set()
    for root, is_default_root in roots:
        for path in sorted(root.rglob("*.json"))[:500]:
            if any(part.casefold() in {"old", "archive", "archived"} for part in path.relative_to(root).parts[:-1]):
                continue
            if path.name.startswith(".") or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 5_000_000:
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            types = set()
            def visit(value):
                if isinstance(value, dict):
                    node_type = value.get("class_type") or (value.get("type") if "widgets_values" in value or "inputs" in value else None)
                    if isinstance(node_type, str):
                        types.add(node_type)
                    for item in value.values():
                        visit(item)
                elif isinstance(value, list):
                    for item in value:
                        visit(item)
            visit(document)
            if not types:
                continue
            from .block_party import imported, load, PackageError
            package = None
            workflow_id = path.relative_to(root).as_posix()
            if imported(workflow_id):
                try:
                    package = load(settings, workflow_id)[0]["manifest"]
                except PackageError:
                    continue  # A detached/changed package is not a heuristic fallback recipe.
            name = path.stem.lower()
            video = bool(re.search(r"video|i2v|t2v|r2v|keyframe|ltx|seamless", name)) or any(re.search(r"savevideo|videocombine", t.lower()) for t in types)
            reference = any(t.lower() in {"loadimage", "loadimagemask"} for t in types) or bool(re.search(r"i2v|r2v|img2img|image.?to.?video|reference|keyframe", name))
            video_reference = any(re.search(r"loadvideo|videoloader", t, re.I) for t in types)
            kind = "video" if video else "image"
            if package:
                kind = package["output_kind"]
                reference = any(slot["class_type"] in {"LoadImage", "LoadImageMask"} for slot in package["inputs"])
                video_reference = any("video" in slot["class_type"].lower() for slot in package["inputs"])
            if kind != output_kind:
                continue
            workflow_id = path.relative_to(root).as_posix()
            if workflow_id in seen_ids:
                continue
            seen_ids.add(workflow_id)
            reason = [f"Saved workflow indicates {kind} output"]
            score = 0
            if source_kind == "image":
                score += 20 if reference else -20
                reason.append("Has image inputs/reference hints" if reference else "No image-reference input detected; inspect before use")
            else:
                score += 5 if not reference else -40
                if reference:
                    reason.append("Has image inputs but this request has no source image; prefer a text-only workflow")
            matches = [word for word in words if word in name]
            score += 6 * len(matches)
            if matches:
                reason.append("Matches requested workflow/provider: " + ", ".join(sorted(matches)))
            if name.startswith("mcp"):
                score += 2
            status = "not checked"
            previous = conversion_cache.get(("defaults/" if is_default_root else "custom/") + workflow_id, {})
            stat = path.stat()
            if previous.get("mtime_ns") == stat.st_mtime_ns and previous.get("size") == stat.st_size:
                if previous.get("successful"):
                    status = "conversion succeeded"
                    score += 8
                elif previous.get("successful") is False:
                    try:
                        age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous["last_conversion_at"])).total_seconds()
                    except (KeyError, TypeError, ValueError):
                        age = float("inf")
                    retry_after = 10 if previous.get("conversion_retryable", True) else 300
                    status = "conversion failed" if age < retry_after else "retry available"
                    if age < retry_after:
                        score -= 100
                    reason.append("Previous inspection failed; retry after service recovery, not a permanent workflow ban")
            if previous.get("mtime_ns") != stat.st_mtime_ns or previous.get("size") != stat.st_size:
                previous = {}  # Evidence from an older graph must not rank its replacement.
            render_successes = int(previous.get("render_success_count", 0))
            render_failures = int(previous.get("render_failure_count", 0))
            if render_successes:
                score += min(20, 5 + render_successes)
                reason.append(f"Render-proven locally ({render_successes} successful run{'s' if render_successes != 1 else ''})")
            if previous.get("last_render_status") == "failed":
                score -= 6
                reason.append("Last render failed: " + str(previous.get("last_render_error") or "unknown error")[:180])
            if is_default_root or path.name.startswith("Darius_"):
                score += 1000
                reason.append("Managed Darius default; preferred before custom workflows")
            candidates.append({"workflow_id": workflow_id, "name": package["name"] if package else path.stem,
                "source": "defaults" if is_default_root else "custom",
                "output_kind_hint": kind, "accepts_images_hint": reference, "score": score, "reasons": reason,
                "accepts_video_hint": video_reference,
                "node_types": sorted(types)[:60], "conversion_status": status, "requires_inspection": True,
                "compatibility": {"conversion": status,
                    "auto_eligibility_hint": "supported" if types and all(item in _auto_node_names() for item in types) else "review_required",
                    "successful_renders": render_successes, "failed_renders": render_failures,
                    "last_render_status": previous.get("last_render_status"),
                    "last_render_at": previous.get("last_render_at"),
                    "last_error": previous.get("last_render_error")}})
    candidates.sort(key=lambda item: (-item["score"], item["workflow_id"].lower()))
    return {"workflows": candidates[:max(1, min(500, int(limit)))],
            "note": "Ranking is task/input compatibility inferred from saved graphs and names, not a quality benchmark. Inspect the chosen workflow to verify required inputs, model availability, and external calls before preparing it."}


def refresh_conversion_failures(settings):
    """A deliberate folder refresh permits reinspection, preserving render evidence."""
    with _cache_lock:
        cache = _conversion_cache(settings)
        for value in cache.values():
            if value.get("successful") is False:
                value["successful"] = None
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(settings.data_dir / "workflow-conversion-status.json", cache)


def _auto_node_names():
    # Lazy import avoids loading provider modules during catalog-only startup.
    from .local_render import LOCAL_NODES
    return LOCAL_NODES
