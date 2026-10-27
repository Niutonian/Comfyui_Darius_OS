"""Versioned, source-bound recipe contracts. Registration never submits a render."""
from datetime import datetime, timezone
import hashlib
import json
import threading
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .atomic_files import atomic_json
from .render_preview import graph_inputs

VERSION = 1
_lock = threading.RLock()


class RecipeRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: str = Field(min_length=1, max_length=300)
    force: bool = False


class RecipeMappingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: str = Field(min_length=1, max_length=300)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    roles: dict[str, Literal["scene", "preserve", "unresolved"]] = Field(max_length=100)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def manifest(graph, roles=None):
    evidence = graph_inputs(graph)
    overrides = roles or {}
    text = evidence["positive"]
    fields = {item["slot"]: {**item, "role": "scene" if len({entry["value"] for entry in text}) <= 1 else "unresolved"} for item in text}
    fields.update({item["slot"]: {**item, "role": "system"} for item in evidence["system"]})
    fields.update({item["slot"]: {**item, "role": "negative"} for item in evidence["negative"]})
    for slot, role in overrides.items():
        if slot not in fields or fields[slot]["role"] in {"system", "negative"} or role not in {"scene", "preserve", "unresolved"}:
            raise ValueError("Mappings may only assign scene/preserve roles to inspected description fields. System and negative instructions are protected.")
        fields[slot]["role"] = role
    scenes = [slot for slot, item in fields.items() if item["role"] == "scene"]
    unresolved = [slot for slot, item in fields.items() if item["role"] == "unresolved"]
    from .trusted_workflows import pure_upscale
    processing = pure_upscale(graph)
    graph_digest = digest(graph)
    contract_digest = digest({"graph": graph_digest, "roles": {slot: item["role"] for slot, item in fields.items()}})
    outputs = [f"{key}.filename_prefix" for key, node in graph.items() if "filename_prefix" in node.get("inputs", {})]
    return {"version": VERSION, "graph_digest": graph_digest, "contract_digest": contract_digest,
            "status": "ready" if not unresolved and (scenes or processing) and outputs else "needs_mapping",
            "fields": list(fields.values()), "scene_slots": scenes, "unresolved_slots": unresolved,
            "protected_slots": [slot for slot, item in fields.items() if item["role"] in {"system", "negative", "preserve"}],
            "image_slots": [item["slot"] for item in evidence["image_inputs"]],
            "video_slots": [f"{key}.{field}" for key, node in graph.items()
                            if "loadvideo" in node.get("class_type", "").lower()
                            for field, value in node.get("inputs", {}).items() if field == "video" and isinstance(value, str)],
            "output_slots": outputs,
            "setting_slots": {name: [f"{key}.{name}" for key, node in graph.items() if isinstance(node.get("inputs", {}).get(name), (str, int, float, bool))]
                              for name in ("width", "height", "steps", "cfg", "fps", "duration", "duration_seconds", "scale_by")},
            "processing_only": processing}


def source(settings, workflow_id):
    from .workflow_catalog import workflow_source_path
    resolved = workflow_source_path(settings, workflow_id)
    root = getattr(settings, "comfy_workflow_defaults_root", None)
    if not resolved or root is None or resolved[0] != root.resolve() or workflow_id.startswith("assistant-"):
        return None
    return resolved[1]


def cache_path(settings, workflow_id):
    return settings.data_dir / "workflow-recipes" / (hashlib.sha256(workflow_id.encode()).hexdigest() + ".json")


def registered(settings, workflow_id):
    path = source(settings, workflow_id)
    if path is None:
        return None
    try:
        from .block_party import imported, load
        if imported(workflow_id):
            load(settings, workflow_id)
        record = json.loads(cache_path(settings, workflow_id).read_text(encoding="utf-8"))
        if not isinstance(record, dict) or not isinstance(record.get("manifest"), dict) or not isinstance(record.get("graph"), dict) or not isinstance(record.get("roles"), dict):
            return None
        if record.get("version") != VERSION or record.get("source_digest") != hashlib.sha256(path.read_bytes()).hexdigest():
            return None
        if record.get("comfy_url") != settings.comfyui_base_url:
            return None
        contract = record["manifest"]
        if not all(isinstance(contract.get(key), list) for key in ("fields", "scene_slots", "protected_slots", "unresolved_slots")):
            return None
        if contract.get("status") not in {"ready", "needs_mapping"} or digest(record["graph"]) != contract.get("graph_digest"):
            return None
        return record
    except (OSError, ValueError, KeyError, TypeError):
        return None


def compiled(settings, workflow_id):
    record = registered(settings, workflow_id)
    if not record:
        return None
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(record["compiled_at"])).total_seconds()
        if not 0 <= age <= 300 or digest(record["graph"]) != record["manifest"]["graph_digest"]:
            return None
        return json.loads(json.dumps(record["graph"]))
    except (KeyError, ValueError, TypeError):
        return None


def register(settings, workflow_id, graph, *, roles=None, expected_source=None):
    path = source(settings, workflow_id)
    if path is None:
        return manifest(graph, roles)
    with _lock:
        source_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_source is not None and expected_source != source_digest:
            raise ValueError("The base workflow changed. Inspect/register its new version before continuing.")
        previous = registered(settings, workflow_id)
        if previous and previous["manifest"]["graph_digest"] != digest(graph):
            previous = None
        effective_roles = roles if roles is not None else (previous or {}).get("roles", {})
        # Node slots can change after ComfyUI upgrades even for the same UI JSON.
        from .block_party import imported, recipe_contract
        is_package = imported(workflow_id)
        fields = {item["slot"] for item in graph_inputs(graph)["positive"]}
        if roles is None and not is_package:
            effective_roles = {slot: role for slot, role in effective_roles.items() if slot in fields}
        contract = manifest(graph, {} if is_package else effective_roles)
        if is_package:
            contract = recipe_contract(settings, workflow_id, graph, effective_roles, contract)
        record = {"version": VERSION, "workflow_id": workflow_id, "source_digest": source_digest,
                  "comfy_url": settings.comfyui_base_url, "compiled_at": datetime.now(timezone.utc).isoformat(),
                  "roles": effective_roles, "manifest": contract, "graph": graph}
        atomic_json(cache_path(settings, workflow_id), record)
        return {**contract, "source_digest": source_digest}


def public_registration(settings, workflow_id):
    record = registered(settings, workflow_id)
    if not record:
        return {"status": "not_registered", "version": VERSION}
    contract = record["manifest"]
    return {"status": contract["status"], "version": VERSION, "source_digest": record["source_digest"],
            "scene_slots": contract["scene_slots"], "protected_slots": contract["protected_slots"],
            "unresolved_slots": contract["unresolved_slots"]}
