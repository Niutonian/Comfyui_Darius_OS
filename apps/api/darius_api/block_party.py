"""Declarative Block Party job adapter. Never imports package code or its approval state."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import threading
import zipfile

from .atomic_files import atomic_json

MAX_UPLOAD = 64 * 1024 * 1024
MAX_JSON = 5_000_000
IMAGE_LOADERS = {"LoadImage": "image", "LoadImageMask": "image"}
VIDEO_LOADERS = {"LoadVideo": "file", "VHS_LoadVideo": "video", "VHS_LoadVideoPath": "video"}
AUDIO_LOADERS = {"LoadAudio": "audio", "VHS_LoadAudioUpload": "audio"}
OUTPUTS = {"SaveImage": "image", "SaveImageAdvanced": "image", "SaveVideo": "video", "VHS_VideoCombine": "video"}
SETTINGS = {"width", "height", "steps", "cfg", "fps", "duration", "duration_seconds", "scale_by", "aspect_ratio", "megapixels"}
_lock = threading.RLock()


class PackageError(ValueError):
    pass


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def relative(value):
    if not isinstance(value, str) or not value or len(value) > 400 or "\\" in value or ":" in value or "\x00" in value:
        raise PackageError("Package contains an unsafe path.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} or part.endswith((".", " ")) for part in value.split("/")):
        raise PackageError("Package contains an unsafe path.")
    return path


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PackageError("Package JSON contains duplicate keys.")
        result[key] = value
    return result


def _record_path(settings, workflow_id):
    return settings.data_dir / "block-party-recipes" / (sha256(workflow_id.encode()).hexdigest() + ".json")


def imported(workflow_id):
    return isinstance(workflow_id, str) and workflow_id.startswith("block-party/")


def load(settings, workflow_id):
    if not imported(workflow_id):
        return None
    from .workflow_catalog import workflow_source_path
    resolved = workflow_source_path(settings, workflow_id)
    try:
        record = json.loads(_record_path(settings, workflow_id).read_text(encoding="utf-8"))
        if not resolved or resolved[0] != settings.comfy_workflow_defaults_root.resolve():
            raise ValueError("source missing")
        graph = _json(resolved[1].read_bytes())
        manifest = record["manifest"]
        identity = digest({"manifest": manifest, "graph": graph})
        if record.get("workflow_id") != workflow_id or identity != record.get("package_digest") or not workflow_id.endswith("-" + identity[:16] + ".json"):
            raise ValueError("changed package")
        return record, graph
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PackageError("This Block Party recipe changed or its contract is missing. Re-import the package; no workflow was executed.") from exc


def import_zip(settings, content):
    if not isinstance(content, bytes) or len(content) > MAX_UPLOAD:
        raise PackageError("Block Party ZIPs are limited to 64 MiB. Export without example inputs/models.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            items = archive.infolist()
            if len(items) > 2000 or sum(item.file_size for item in items) > 512 * 1024 * 1024:
                raise PackageError("Package has too many entries or expands beyond 512 MiB.")
            names = {}
            for item in items:
                # ZipInfo normalizes backslashes on Windows and truncates NULs.
                # Validate the original archive spelling, not just its cleaned name.
                relative(item.orig_filename.rstrip("/"))
                name = item.filename.rstrip("/")
                relative(name)
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode) or item.flag_bits & 1:
                    raise PackageError("Links and encrypted entries are not supported in recipe packages.")
                if name.casefold() in names:
                    raise PackageError("Package contains ambiguous duplicate paths.")
                names[name.casefold()] = item
            candidates = [item for item in items if not item.is_dir() and PurePosixPath(item.filename).name == "manifest.json"]
            if len(candidates) != 1:
                raise PackageError("Import one exported Block Party job ZIP containing exactly one manifest.json; export project stages separately.")
            entry = candidates[0]
            def read_json(item):
                if item.file_size > MAX_JSON:
                    raise PackageError("Manifest or API graph is too large (5 MB maximum each).")
                with archive.open(item) as stream:
                    return _json(stream.read(MAX_JSON + 1))
            raw = read_json(entry)
            workflows = raw.get("workflows")
            if not isinstance(workflows, list) or len(workflows) != 1 or not isinstance(workflows[0], dict):
                raise PackageError("Export one job with one API workflow. Multi-workflow project chains are not imported as a single recipe.")
            child = relative(workflows[0].get("file"))
            graph_name = (PurePosixPath(entry.filename).parent / child).as_posix()
            graph_entry = names.get(graph_name.casefold())
            if not graph_entry or graph_entry.is_dir() or graph_entry.filename != graph_name:
                raise PackageError("The API graph declared by manifest.json is missing or ambiguously named.")
            graph = read_json(graph_entry)
            manifest = validate_manifest(raw, graph)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError, EOFError) as exc:
        raise PackageError("The Block Party ZIP could not be read. Export a new job package.") from exc
    identity = digest({"manifest": manifest, "graph": graph})
    slug = re.sub(r"[^a-z0-9]+", "-", manifest["name"].lower()).strip("-")[:60] or "recipe"
    workflow_id = f"block-party/{slug}-{identity[:16]}.json"
    root = settings.comfy_workflow_defaults_root
    if root is None:
        raise PackageError("Configure DARIUS_WORKFLOW_DEFAULTS_DIR before importing recipes.")
    root = root.resolve()
    target = root / workflow_id
    if not target.resolve().is_relative_to(root) or target.parent.is_symlink() or target.is_symlink():
        raise PackageError("The managed recipe folder has an unsafe link.")
    with _lock:
        existing = target.exists()
        if existing:
            load(settings, workflow_id)  # Never overwrite a changed source under the same ID.
        else:
            record = {"version": 1, "workflow_id": workflow_id, "package_digest": identity,
                      "graph_digest": digest(graph), "manifest": manifest}
            atomic_json(_record_path(settings, workflow_id), record)
            atomic_json(target, graph)  # Publish the graph last; imported state/examples are never extracted.
        from .workflow_registration import register
        registration = register(settings, workflow_id, graph)
    return {"workflow_id": workflow_id, "name": manifest["name"], "already_imported": existing,
            "registration": registration, "output_kind": manifest["output_kind"],
            "note": "Imported recipe contract only. No examples, scripts, approval state, models or jobs were imported; no render or installation started."}


def recipe_contract(settings, workflow_id, graph, roles, base):
    package = load(settings, workflow_id)
    if package is None:
        return base
    record, original = package
    if digest(graph) != record["graph_digest"]:
        raise PackageError("The imported API graph does not match its Block Party contract. Re-import it.")
    declared = record["manifest"]
    specs = {f"{item['node_id']}.{item['key']}": item for item in declared["parameters"]}
    fields = {item["slot"]: deepcopy(item) for item in base["fields"]}
    protected = {key for key, item in fields.items() if item["role"] in {"system", "negative"}}
    settings_slots = {slot for slot, spec in specs.items() if spec["name"] in SETTINGS or spec["key"] in SETTINGS}
    texts = {slot: spec for slot, spec in specs.items() if spec["type"] == "string" and slot not in protected
             and slot not in settings_slots}
    preferred = [slot for slot, spec in texts.items() if spec["name"] in {"text", "prompt"} and slot in fields]
    if not preferred and len(texts) == 1:
        preferred = [slot for slot in texts if slot in fields]
    for slot, field in fields.items():
        if slot not in protected:
            field["role"] = "scene" if slot in preferred else "preserve" if slot not in texts else "unresolved"
            field["editable"] = slot in texts
    for slot, spec in texts.items():
        if slot not in fields:
            fields[slot] = {"slot": slot, "label": spec["name"], "value": spec["default"], "role": "unresolved", "editable": True}
    for slot, role in (roles or {}).items():
        if slot in settings_slots and role in {"preserve", "unresolved"}:
            continue  # Compatible with older saved maps; settings aren't scene text.
        if slot not in texts or role not in {"scene", "preserve", "unresolved"}:
            # Older UI sends every displayed preserve field; retain it, never expose it.
            if slot in fields and role == fields[slot]["role"] == "preserve":
                continue
            raise PackageError("Only declared Block Party text parameters can receive scene mappings. Re-export to expose another input.")
        fields[slot]["role"] = role
    result = deepcopy(base)
    result.update(fields=list(fields.values()), scene_slots=[key for key, item in fields.items() if item["role"] == "scene"],
                  unresolved_slots=[key for key, item in fields.items() if item["role"] == "unresolved"],
                  protected_slots=[key for key, item in fields.items() if item["role"] in {"preserve", "negative", "system"}],
                  setting_slots={key: [slot for slot, spec in specs.items() if spec["name"] == key or spec["key"] == key] for key in SETTINGS},
                  block_party={"name": declared["name"], "package_digest": record["package_digest"],
                               "inputs": declared["inputs"], "parameters": declared["parameters"], "output_kind": declared["output_kind"]})
    result["status"] = "ready" if not result["unresolved_slots"] and (result["scene_slots"] or result["processing_only"]) and result["output_slots"] else "needs_mapping"
    result["contract_digest"] = digest({"graph": result["graph_digest"], "package": record["package_digest"], "roles": {key: item["role"] for key, item in fields.items()}})
    return result


def enforce_overrides(contract, overrides, bindings):
    declared = contract.get("block_party")
    if not declared:
        return
    specs = {f"{item['node_id']}.{item['key']}": item for item in declared["parameters"]}
    for slot, value in overrides.items():
        if slot not in specs:
            raise PackageError("This input was not exposed by the Block Party author. Re-export the job to make it editable.")
        check_value(specs[slot], value)
    image_slots = {f"{item['node_id']}.{item['key']}" for item in declared["inputs"] if item["class_type"] in IMAGE_LOADERS}
    if set(bindings) != image_slots:
        raise PackageError("Bind every declared Block Party image input to this project's assets; bundled examples are not references.")


def prepare_declared_seeds(graph, contract, mode, overrides):
    from secrets import randbelow
    from .workflows import resolve_graph_slot
    if mode not in {"randomize", "preserve"}:
        raise PackageError("Seed mode must be randomize or preserve.")
    for spec in contract["block_party"]["parameters"]:
        if spec["type"] != "seed":
            continue
        slot = f"{spec['node_id']}.{spec['key']}"
        if mode == "randomize" and slot not in overrides:
            node, key = resolve_graph_slot(graph, slot)
            graph[node]["inputs"][key] = randbelow(2**32)


def _json(raw):
    if len(raw) > MAX_JSON:
        raise PackageError("Manifest or API graph is too large (5 MB maximum each).")
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(PackageError("Non-finite JSON values are not supported.")))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise PackageError("Package contains invalid JSON.") from exc
    if not isinstance(value, dict):
        raise PackageError("Manifest and API graph must be JSON objects.")
    _secrets(value)
    return value


def _secrets(value, depth=0):
    if depth > 40:
        raise PackageError("Package JSON is too deeply nested.")
    if isinstance(value, dict):
        for key, item in value.items():
            if re.search(r"^(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|authorization|secret|credential)s?$", str(key), re.I) and item:
                raise PackageError("Remove embedded credentials before exporting this package.")
            _secrets(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _secrets(item, depth + 1)
    elif isinstance(value, str) and re.search(r"\bsk-[A-Za-z0-9_-]{16,}|https?://[^\s/]+:[^\s/]+@|[?&](?:token|api_key|key|signature)=", value, re.I):
        raise PackageError("Remove embedded credentials or signed URLs before exporting this package.")


def _target(graph, spec):
    if not isinstance(spec, dict):
        raise PackageError("Every declared slot must be an object.")
    node_id, key = str(spec.get("node_id", "")), spec.get("key")
    node = graph.get(node_id)
    if not isinstance(node, dict) or node.get("class_type") != spec.get("class_type") or not isinstance(key, str) or key not in node["inputs"]:
        raise PackageError("A declared parameter/input does not match its exact graph node, class and key.")
    return f"{node_id}.{key}", node["inputs"][key]


def check_value(spec, value):
    kind = spec["type"]
    valid = ((kind == "string" and isinstance(value, str)) or (kind == "boolean" and type(value) is bool)
             or (kind in {"integer", "seed"} and type(value) is int) or (kind == "number" and type(value) in {int, float}))
    if kind == "seed" and value == "random":
        return
    if not valid or isinstance(value, (float, int)) and not math.isfinite(value):
        raise PackageError(f"Parameter {spec['name']} has an invalid value type.")
    if kind in {"integer", "number", "seed"}:
        low, high = (0, 2**32 - 1) if kind == "seed" else (spec["min"], spec["max"])
        if not low <= value <= high:
            raise PackageError(f"Parameter {spec['name']} is outside its declared bounds.")
        if kind != "seed" and not math.isclose((value - low) / spec["step"], round((value - low) / spec["step"]), abs_tol=1e-6):
            raise PackageError(f"Parameter {spec['name']} does not match its declared step.")


def validate_manifest(raw, graph):
    if not graph or len(graph) > 500 or any(not isinstance(node, dict) or not isinstance(node.get("class_type"), str)
            or not isinstance(node.get("inputs"), dict) for node in graph.values()):
        raise PackageError("Export an API-format graph with 1–500 nodes, not a ComfyUI canvas document.")
    name = raw.get("name", "Block Party recipe")
    if not isinstance(name, str) or not 1 <= len(name) <= 100:
        raise PackageError("The package needs a short name.")
    result = {"name": name}
    for key in ("models", "nodes", "parameters", "runtime_requirements", "model_mappings"):
        items = raw.get(key, [])
        if not isinstance(items, list) or len(items) > 500 or any(not isinstance(item, dict) for item in items):
            raise PackageError(f"Invalid {key} declaration.")
        result[key] = deepcopy(items)
    media_targets, parameter_targets = set(), set()
    loaders = {**IMAGE_LOADERS, **VIDEO_LOADERS, **AUDIO_LOADERS}
    for group in ("inputs", "outputs"):
        items = raw.get(group, [raw[group[:-1]]] if group[:-1] in raw else [])
        if not isinstance(items, list) or len(items) > 30:
            raise PackageError(f"Invalid {group} declaration.")
        result[group] = []
        names = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise PackageError("Invalid media slot.")
            item = deepcopy(item)
            item.setdefault("name", f"{group}_{index}")
            if not isinstance(item["name"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item["name"]) or item["name"] in names:
                raise PackageError("Media slot names must be short and unique.")
            names.add(item["name"])
            node = graph.get(str(item.get("node_id", "")), {})
            if node.get("class_type") != item.get("class_type"):
                raise PackageError("A declared media slot does not match the graph.")
            if group == "inputs":
                slot, value = _target(graph, item)
                if loaders.get(item["class_type"]) != item["key"] or not isinstance(value, str) or slot in media_targets:
                    raise PackageError("Unsupported or duplicate media input. Export a supported image/video/audio loader.")
                media_targets.add(slot)
            elif item["class_type"] not in OUTPUTS or "filename_prefix" not in node.get("inputs", {}):
                raise PackageError("Unsupported output. Use a SaveImage/SaveVideo-compatible output node.")
            result[group].append(item)
    expected = {f"{node_id}.{loaders[node['class_type']]}" for node_id, node in graph.items() if node['class_type'] in loaders}
    if expected != media_targets:
        raise PackageError("The manifest must declare every supported media input; example files cannot be reused implicitly.")
    kinds = {OUTPUTS[item["class_type"]] for item in result["outputs"]}
    if len(kinds) != 1:
        raise PackageError("Export one job with one output kind (image or video). Split mixed-output jobs first.")
    result["output_kind"] = next(iter(kinds))
    names = set()
    for spec in result["parameters"]:
        slot, baked = _target(graph, spec)
        if not isinstance(spec.get("name"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", spec["name"]) or spec["name"] in names or slot in parameter_targets:
            raise PackageError("Editable parameter names and targets must be unique.")
        names.add(spec["name"]); parameter_targets.add(slot)
        if spec.get("type") not in {"string", "integer", "number", "boolean", "seed"} or "default" not in spec:
            raise PackageError("Invalid editable parameter type/default.")
        if isinstance(baked, (list, dict)) or baked is None or slot in media_targets or spec["key"] == "filename_prefix" or (isinstance(baked, str) and re.search(r"\.(?:safetensors|gguf|ckpt|pt|pth|bin)$", baked, re.I)):
            raise PackageError("Connections, model selectors, filenames and media inputs cannot be exposed as editable parameters.")
        if re.fullmatch(r"(?:model|ckpt|unet|clip|vae|lora|mmproj)_name|checkpoint|filename|file_path|url", spec["key"], re.I):
            raise PackageError("Model selectors and file locations are fixed dependency declarations, not editable parameters.")
        if spec["type"] == "seed" and spec["key"] not in {"seed", "noise_seed"}:
            raise PackageError("Seed parameters must target seed or noise_seed inputs.")
        if spec["type"] in {"integer", "number"}:
            if any(type(spec.get(k)) not in {int, float} or not math.isfinite(spec[k]) for k in ("min", "max", "step")) or spec["min"] > spec["max"] or spec["step"] <= 0:
                raise PackageError("Numeric parameters need finite min/max/step bounds.")
        check_value(spec, spec["default"])
        if spec["type"] == "seed" and spec["default"] == "random":
            # Block Party intentionally ignores the saved graph's seed when
            # the author exposes a random seed. Legacy ComfyUI seeds may be
            # wider than Block Party's generated/explicit 32-bit seed range.
            if type(baked) is not int:
                raise PackageError("Random seed targets must already be integers in the graph.")
        else:
            check_value(spec, baked)
            if spec["default"] != baked or type(spec["default"]) is bool and type(baked) is not bool:
                raise PackageError("Parameter defaults must match the exported graph.")
    for model in result["models"]:
        relative(model.get("filename")); relative(model.get("folder"))
        if not re.fullmatch(r"[a-fA-F0-9]{64}", str(model.get("sha256", ""))):
            raise PackageError("Every model must declare its full SHA256. Prepare/re-export the Block Party job.")
    model_names = {model["filename"] for model in result["models"]}
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, str) and re.search(r"\.(?:safetensors|gguf|ckpt|pt|pth|bin)$", value, re.I) and value not in model_names:
                raise PackageError("A model file used by the graph is absent from the dependency manifest. Prepare/re-export the complete job.")
    declared_classes = set()
    for node in result["nodes"]:
        path = relative(node.get("name"))
        if len(path.parts) != 1 or not re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", str(node.get("commit", ""))) or not isinstance(node.get("class_types"), list):
            raise PackageError("Custom node packs need a folder name, exact commit and class list.")
        if any(not isinstance(name, str) or not name or len(name) > 200 or name in declared_classes for name in node["class_types"]):
            raise PackageError("Each declared custom node class must have one unambiguous owning pack.")
        declared_classes.update(node["class_types"])
    return result
