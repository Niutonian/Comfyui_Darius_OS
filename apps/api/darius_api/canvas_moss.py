"""Versioned allowlist adapter for the user's verified MOSS bounding-box graph."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import urllib.request

from .canvas_document import CanvasContent, CanvasRegion, Artboard, PRESETS, compile_regions

VERSION = "moss-bboxes-v1"
SOURCE_DIGEST = "3e2dc435a1509ad3ac8d31a45a1d7d2ed01e007c5cad0a48c17b2d00f0c09f0b"
SOURCE_UI_DIGEST = "2077e236a84a8518e4614a35f7cb52b2a1b953da226c51eee02246e89f08ca0d"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def template(settings):
    path = settings.repository_root / "workflows" / "canvas" / VERSION / "source.api.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    if digest(graph) != SOURCE_DIGEST:
        raise ValueError("The Canvas source template changed; register a new adapter version before generating")
    return graph


def compile_graph(settings, content: CanvasContent, seed: int):
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Canvas seeds must be integers between 0 and 4,294,967,295")
    boxes, index_map, characters = compile_regions(content)
    graph = deepcopy(template(settings))
    graph["19"]["inputs"]["aspect_ratio"] = PRESETS[content.artboard.preset][0]
    graph["25"]["inputs"]["editor_state"] = {"__value__": boxes}
    graph["25"]["inputs"]["last_incoming"] = {"__value__": []}
    graph["27"]["inputs"].update(prompt=content.globalPrompt, character_boxes=characters)
    graph["18:16"]["inputs"]["switch"] = False
    graph["18:7"]["inputs"]["seed"] = seed
    graph["9"]["inputs"]["filename_prefix"] = "darius/canvas/pending"
    provenance = {"adapterVersion": VERSION, "sourceGraphDigest": SOURCE_DIGEST, "sourceUiDigest": SOURCE_UI_DIGEST,
        "preparedGraphDigest": digest(graph), "regionIndexMap": index_map, "characterBoxes": characters,
        "width": content.artboard.width, "height": content.artboard.height, "seed": seed,
        "steps": 25, "cfg": 2.5, "sampler": "er_sde", "scheduler": "simple", "enhancement": False,
        "samplerInputs": {k: v for k, v in graph["18:7"]["inputs"].items() if not isinstance(v, list)},
        "models": {role: deepcopy(graph[node]["inputs"]) for role, node in (("diffusion", "18:1"), ("textEncoder", "18:2"), ("vae", "18:3"))},
        "skipLayerGuidance": {"enabled": graph["18:32"]["inputs"]["switch"],
            **{k: v for k, v in graph["18:15"]["inputs"].items() if k != "model"}},
        "capabilities": {"wholeComposition": True, "references": False, "pixelProtection": False, "independentLayers": False}}
    return graph, provenance


def runtime_environment(settings):
    """Best-effort runtime identity; never log startup arguments or filesystem paths."""
    try:
        with urllib.request.urlopen(settings.comfyui_base_url.rstrip("/") + "/system_stats", timeout=3) as response:
            stats = json.load(response)
        system = stats.get("system") or {}
        return {"system": {k: system[k] for k in ("comfyui_version", "python_version", "pytorch_version", "os") if k in system},
            "devices": [{k: d[k] for k in ("name", "type", "index", "vram_total") if k in d} for d in stats.get("devices", [])]}
    except Exception:
        return {"unavailable": True, "note": "ComfyUI runtime identity could not be read; no environment was inferred."}


def example(settings):
    source = template(settings)
    rows = source["25"]["inputs"]["editor_state"]["__value__"]
    content = CanvasContent(name="MOSS · imported example", artboard=Artboard(), globalPrompt=source["27"]["inputs"]["prompt"],
        regions=[CanvasRegion(id=f"example-{i+1}", parentId=None, name=(row["metadata"].get("text") or f"Object {i+1}").split("\n")[0][:60],
            kind="text" if row["metadata"]["type"] == "text" else "character" if str(i+1) in source["27"]["inputs"]["character_boxes"].split(",") else "object",
            x=row["x"]/1024, y=row["y"]/1024, width=row["width"]/1024, height=row["height"]/1024,
            order=i, description=row["metadata"].get("desc", ""), text=row["metadata"].get("text", "")) for i, row in enumerate(rows)])
    return {"content": content.model_dump(), "warnings": [
        "Imported current editor_state, not last_incoming. Some example descriptions conflict with their geometry; review placement prose. Geometry is authoritative.",
        "The original character annotation marks row 1, which is text. It was not reassigned to another row by guesswork."]}


def readiness(settings, graph=None):
    from .providers import ComfyMcpProvider
    graph = graph or template(settings)
    schemas = ComfyMcpProvider(settings).live_node_schemas(graph)
    issues = []
    for node in graph.values():
        if node["class_type"] not in schemas:
            issues.append("Missing node: " + node["class_type"])
    for node_id, key in (("18:1", "unet_name"), ("18:2", "clip_name"), ("18:3", "vae_name")):
        node = graph[node_id]
        spec = schemas.get(node["class_type"], {}).get("input", {}).get("required", {}).get(key, [])
        choices = spec[0] if spec and isinstance(spec[0], list) else (spec[1].get("options", []) if len(spec) > 1 and isinstance(spec[1], dict) else [])
        if node["inputs"][key] not in choices:
            issues.append("Missing or unavailable model: " + node["inputs"][key])
    return {"ready": not issues, "issues": issues, "adapterVersion": VERSION,
            "note": "Installed node/model names checked. No installation, model loading or render was started; this is not a VRAM guarantee."}
