"""Read-only dependency checks. No installers, model loading or remote downloads."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import os
import subprocess
import threading
from urllib.parse import urlparse

from .block_party import load, relative, digest, PackageError

_lock = threading.Lock()
_hashes = {}


def comfy_root(settings):
    from .comfy_connection import effective_settings
    settings = effective_settings(settings)
    explicit = getattr(settings, "block_party_comfy_root", None)
    root = explicit or (settings.comfyui_output_dir.parent if settings.comfyui_output_dir else None)
    if root:
        root = Path(root).resolve()
        if (root / "main.py").is_file() and (root / "folder_paths.py").is_file():
            return root
    return None


def _hash_file(path):
    before = path.stat()
    identity = (str(path), before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    with _lock:
        if identity in _hashes:
            return _hashes[identity]
    value = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            value.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino):
        raise PackageError("A model changed during verification. Check dependencies again.")
    with _lock:
        if len(_hashes) >= 256:
            _hashes.clear()
        _hashes[identity] = value.hexdigest()
    return value.hexdigest()


def _git(pack, *args):
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(pack), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise PackageError("The declared node pack is not an inspectable Git checkout.")
    return result.stdout.strip()


def check_readiness(settings, workflow_id, *, graph=None):
    record, original = load(settings, workflow_id)
    if graph is not None and digest(graph) != record["graph_digest"]:
        raise PackageError("The recipe graph changed; re-import the package.")
    manifest = record["manifest"]
    issues, warnings, checked = [], [], {"models": 0, "node_packs": 0, "node_classes": 0}
    def issue(code, message):
        issues.append({"code": code, "message": message})
    root = comfy_root(settings)
    if root is None and (manifest["models"] or manifest["nodes"]):
        issue("comfy_root_required", "Set BLOCK_PARTY_COMFY_ROOT to this server's ComfyUI folder (or configure COMFYUI_OUTPUT_DIR) to verify dependency files")
    if root:
        aliases = {"unet": ("diffusion_models", "unet"), "diffusion_models": ("diffusion_models", "unet"),
                   "clip": ("text_encoders", "clip"), "text_encoders": ("text_encoders", "clip")}
        for model in manifest["models"]:
            try:
                folder, filename = relative(model["folder"]), relative(model["filename"])
                candidates = [root / "models" / name / filename for name in aliases.get(str(folder), (str(folder),))]
                candidates = [path.resolve() for path in candidates if path.resolve().is_relative_to(root / "models") and path.is_file()]
                if not candidates:
                    issue("missing_model", f"Missing declared model {folder}/{filename}; prepare it in Block Party (external model-path mappings are not inferred)")
                    continue
                if not any(_hash_file(path) == model["sha256"].lower() for path in candidates):
                    issue("model_hash_mismatch", f"Model hash mismatch for {folder}/{filename}; install the exact exported model")
                    continue
                checked["models"] += 1
            except (OSError, PackageError):
                issue("model_verification_failed", "A declared model could not be verified; check its file permissions and package")
        for pack in manifest["nodes"]:
            try:
                path = (root / "custom_nodes" / relative(pack["name"])).resolve()
                if not path.is_relative_to(root / "custom_nodes") or not path.is_dir():
                    issue("missing_node_pack", f"Missing node pack {pack['name']}; prepare it in Block Party")
                elif Path(_git(path, "rev-parse", "--show-toplevel")).resolve() != path:
                    issue("node_verification_failed", f"{pack['name']} is not its own pinned Git checkout")
                elif _git(path, "rev-parse", "HEAD").lower() != pack["commit"].lower():
                    issue("node_revision_mismatch", f"Node pack {pack['name']} does not match the exported commit")
                elif _git(path, "status", "--porcelain", "--untracked-files=normal"):
                    issue("node_pack_modified", f"Node pack {pack['name']} has local changes; verify/re-export its intended version")
                else:
                    checked["node_packs"] += 1
            except (OSError, subprocess.SubprocessError, PackageError):
                issue("node_verification_failed", f"Could not verify the installed revision of {pack['name']}")
    endpoint = urlparse(settings.comfyui_base_url)
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"} or endpoint.username or endpoint.password:
        issue("local_comfy_required", "Dependency checks require this server's loopback ComfyUI endpoint")
    else:
        from .providers import ComfyMcpProvider, ProviderError
        try:
            schemas = ComfyMcpProvider(settings).live_node_schemas(original)
            for node_type in {node["class_type"] for node in original.values()}:
                metadata = schemas.get(node_type, {})
                owners = [pack for pack in manifest["nodes"] if node_type in pack["class_types"]]
                module = metadata.get("python_module", "")
                if not module:
                    issue("node_origin_unavailable", f"The loaded origin of {node_type} could not be verified")
                elif module.startswith("custom_nodes.") and (len(owners) != 1 or module != "custom_nodes." + owners[0]["name"]):
                    issue("node_origin_mismatch", f"{node_type} is not loaded from its declared node pack")
                elif owners and module != "custom_nodes." + owners[0]["name"]:
                    issue("node_origin_mismatch", f"{node_type} is not loaded from its declared node pack")
                else:
                    checked["node_classes"] += 1
        except ProviderError:
            issue("comfy_nodes_unavailable", "Start ComfyUI and check that every declared node is installed and loaded")
    unsupported = [item["name"] for item in manifest["inputs"] if item["class_type"] not in {"LoadImage", "LoadImageMask"}]
    if unsupported:
        issue("unsupported_media_binding", "Darius currently binds project images only; video/audio inputs need adapter support: " + ", ".join(unsupported))
    if manifest["runtime_requirements"]:
        warnings.append("Additional runtime dependencies are declared. Prepare/check them in Block Party; Darius does not import modules to test them.")
    from .local_render import LOCAL_NODES
    unknown = sorted({node["class_type"] for node in original.values()} - LOCAL_NODES.keys())
    if unknown:
        warnings.append("These nodes still need explicit render review: " + ", ".join(unknown))
    return {"ready": not issues, "issues": issues, "warnings": warnings, "checked": checked,
            "package_digest": record["package_digest"], "checked_at": datetime.now(timezone.utc).isoformat(),
            "note": "Checks do not install dependencies, start a render, grant execution permission, or guarantee available VRAM."}
