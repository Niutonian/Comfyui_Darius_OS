"""Immutable FIBO profiles for the supplied layout → string conditioning chain."""
from copy import deepcopy
import hashlib
import json
import subprocess

from .canvas_document import CanvasContent, CanvasRegion, compile_regions, dimensions
from .canvas_moss import digest

LEGACY_FAST = "fibo-fast-experimental-v1"
FAST = "fibo-fast-turbo-v2"
DEV = "fibo-dev-v1"
COMPILER = "fibo-layout-string-v1"
PROFILES = {
    FAST: {"id": FAST, "name": "Fast preview · Turbo · experimental", "family": "fibo", "steps": 4, "cfg": 1,
           "templateDigest": "fd170ef39e91a440c16f1e1d2c1c09ccc6bc5251160c713f2f06b1d99f2870c7",
           "manifestDigest": "c3936458b70db5f5068a2090fa3fcfe3fbcf45e1314423e06d9c619413778d13"},
    LEGACY_FAST: {"id": LEGACY_FAST, "name": "Fast preview · legacy Dev weights", "family": "fibo", "steps": 4, "cfg": 1, "deprecated": True,
           "templateDigest": "bbe8ee8a677d8219cf0665d58a6eaaeb8801208daa463493ddd9d24bfd1cf3df",
           "manifestDigest": "6d4192bfab07d797be9c794da7fddb89d7e146022010823be012965895394539"},
    DEV: {"id": DEV, "name": "Dev render", "family": "fibo", "steps": 30, "cfg": 5,
          "templateDigest": "36c5e833757022cd316546ace25e7245e54163f1aa5c67893f8351b2abc413d9",
          "manifestDigest": "1036667cd294900f4556713c6234de9618a3fa2cbf1325350f8003c909328aa4"},
}


def text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def local_model_fingerprints(settings, profile=DEV):
    """Cheap, explicitly labelled identity hints; never pretend these are full hashes."""
    root = settings.block_party_comfy_root or (settings.comfyui_output_dir.parent if settings.comfyui_output_dir else None)
    result = {}
    if root is None:
        return {"available": False, "reason": "No local ComfyUI checkout configured"}
    diffusion = "fibo2_edit_turbo_int8_convrot.safetensors" if profile == FAST else "fibo2_dev_int8_convrot.safetensors"
    for folder, name in (("diffusion_models", diffusion),
                         ("text_encoders", "qwen3vl_4b_bf16.safetensors"), ("vae", "flux2-vae.safetensors")):
        path = root / "models" / folder / name
        try:
            stat = path.stat()
            with path.open("rb") as handle:
                header = hashlib.sha256(handle.read(65536)).hexdigest()
            result[name] = {"bytes": stat.st_size, "mtimeNs": str(stat.st_mtime_ns), "first64KiBSha256": header,
                            "scheme": "size+mtime+header; not a full weights checksum"}
        except OSError:
            result[name] = {"available": False}
    try:
        result["localCheckoutCommit"] = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
            timeout=3, stderr=subprocess.DEVNULL, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).strip()
    except (OSError, subprocess.SubprocessError):
        result["localCheckoutCommit"] = None
    return result


def seed_value(value, *, maximum=2**64-1):
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"Seed must be a whole number between 0 and {maximum:,}")
    return value


def artifacts(settings, profile):
    if profile not in PROFILES:
        raise ValueError("Unknown FIBO profile")
    directory = settings.repository_root / "workflows" / "canvas" / profile
    load = lambda name: json.loads((directory / name).read_text(encoding="utf-8"))
    manifest, graph, prompt = load("manifest.json"), load("template.api.json"), load("prompt-template.json")
    if (digest(manifest) != PROFILES[profile]["manifestDigest"] or manifest["profileId"] != profile or manifest["compilerVersion"] != COMPILER
            or digest(graph) != PROFILES[profile]["templateDigest"]
            or digest(graph) != manifest["templateDigest"] or digest(prompt) != manifest["promptTemplateDigest"]
            or digest(load("source.api.json")) != manifest["sourceGraphDigest"]):
        raise ValueError("FIBO profile artifacts changed; register a new profile/compiler version")
    return manifest, graph, prompt


def elements_for(boxes, width, height):
    """Equivalent to installed CreateBoundingBoxes.build_elements (ties-to-even)."""
    result = []
    for box in boxes:
        x, y, w, h = box["x"] / width, box["y"] / height, box["width"] / width, box["height"] / height
        values = [round(v * 1000) for v in (y, x, y + h, x + w)]
        if any(not 0 <= v <= 1000 for v in values) or values[2] <= values[0] or values[3] <= values[1]:
            raise ValueError("A region is outside the FIBO grid or smaller than one normalized grid cell")
        meta = box["metadata"]
        element = {"type": meta["type"], "bbox": values}
        if meta["type"] == "text":
            element["text"] = meta["text"]
        element["desc"] = meta["desc"]
        if meta["palette"]:
            element["color_palette"] = [color.upper() for color in meta["palette"]]
        result.append(element)
    return result


def compile_graph(settings, content: CanvasContent, seed, profile=DEV, source=None):
    manifest, graph, prompt_template = artifacts(settings, profile)
    seed = seed_value(seed)
    width, height = content.artboard.width, content.artboard.height
    if (width, height) != dimensions(content.artboard.preset):
        raise ValueError("Artboard dimensions must match the selected Canvas preset")
    boxes, index_map, _ = compile_regions(content, palettes=True)
    elements = elements_for(boxes, content.artboard.width, content.artboard.height)
    instruction = prompt_template["beforeScene"] + content.globalPrompt + prompt_template["afterScene"]
    # Installed KJ SomethingToString joins str(dict) values without outer brackets.
    exact_prompt = instruction + "\n" + ", ".join(str(element) for element in elements)
    composition = {"content": content.model_dump(), "boxes": boxes, "elements": elements,
                   "conditioningPrompt": exact_prompt, "negativePrompt": "", "seed": str(seed),
                   "width": width, "height": height, "batchSize": 1}
    if source is not None:
        if (source.get("profileId") not in {FAST, LEGACY_FAST} or profile != DEV or source.get("compilerVersion") != COMPILER
                or source.get("promptTemplateDigest") != manifest["promptTemplateDigest"]
                or source.get("compositionInputHash") != digest(composition)
                or source.get("conditioningPrompt") != exact_prompt
                or source.get("conditioningPromptHash") != text_hash(exact_prompt)
                or source.get("documentSnapshot") != content.model_dump()):
            raise ValueError("This preview's saved compiler/snapshot is not compatible with the registered Dev profile")
        # Authoritative historical bytes, after full compatibility validation.
        exact_prompt = source["conditioningPrompt"]
    graph = deepcopy(graph)
    graph["17"]["inputs"].update(width=width, height=height, editor_state={"__value__": boxes}, last_incoming={"__value__": []})
    graph["19"]["inputs"].update(string=instruction, strip_newlines=False)
    graph["18"]["inputs"].update(prefix="", suffix="")
    graph["20"]["inputs"]["delimiter"] = "\n"
    graph["4"]["inputs"].update(width=width, height=height, batch_size=1, negative_prompt="")
    sampler, sink = manifest["sampler"], manifest["outputNode"]
    graph[sampler]["inputs"]["seed"] = seed
    graph[sink]["inputs"]["filename_prefix"] = "darius/canvas/pending"
    provenance = {**manifest, "adapterVersion": profile, "profileVersion": 2 if profile == FAST else 1, "profileName": PROFILES[profile]["name"],
        "documentSnapshot": content.model_dump(), "conditioningPrompt": exact_prompt, "conditioningPromptHash": text_hash(exact_prompt),
        "negativePrompt": "", "compositionInputHash": digest(composition), "flattenedBoxes": boxes,
        "normalizedElements": elements, "regionIndexMap": index_map, "width": width, "height": height,
        "batchSize": 1, "seed": str(seed), "steps": PROFILES[profile]["steps"], "cfg": PROFILES[profile]["cfg"],
        "samplerName": "euler", "scheduler": "simple", "denoise": 1,
        "models": {role: deepcopy(graph[node]["inputs"]) for role, node in (("diffusion", manifest["loader"]), ("textEncoder", "2"), ("vae", "3"))},
        "availableModelFingerprints": local_model_fingerprints(settings, profile),
        "preparedGraphDigest": digest(graph), "capabilities": {"wholeComposition": True, "references": False, "pixelProtection": False}}
    provenance["executionProfileHash"] = digest({"profileId": profile, "templateDigest": manifest["templateDigest"], "graph": graph})
    return graph, provenance


def readiness(settings, graph=None, profile=DEV):
    from .providers import ComfyMcpProvider
    manifest, original, _ = artifacts(settings, profile)
    graph = graph or original
    schemas = ComfyMcpProvider(settings).live_node_schemas(graph)
    issues = ["Missing node: " + node["class_type"] for node in graph.values() if node["class_type"] not in schemas]
    for node_id, field in ((manifest["loader"], "unet_name"), ("2", "clip_name"), ("3", "vae_name")):
        node = graph[node_id]
        spec = schemas.get(node["class_type"], {}).get("input", {}).get("required", {}).get(field, [])
        choices = spec[0] if spec and isinstance(spec[0], list) else (spec[1].get("options", []) if len(spec) > 1 else [])
        if node["inputs"][field] not in choices:
            issues.append("Missing model: " + node["inputs"][field])
    return {"ready": not issues, "issues": issues, "adapterVersion": profile,
            "note": "Installed nodes/model names checked; no render started. Fast preview uses Turbo weights; Dev render uses Dev weights."}


def example(settings, profile=DEV):
    manifest, graph, _ = artifacts(settings, profile)
    # The CLI conversion drops V3 socketless BoundingBoxes widgets. Recover the
    # explicit example from its immutable UI snapshot, never from empty API defaults.
    directory = settings.repository_root / "workflows" / "canvas" / profile
    raw = (directory / "source.ui.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["sourceUiDigest"]:
        raise ValueError("The supplied example snapshot changed; register a new source version")
    node = next(n for n in json.loads(raw)["nodes"] if str(n["id"]) == "17")
    boxes = node["widgets_values_named"]["editor_state"]
    instruction = graph["19"]["inputs"]["string"]
    scene = instruction.split("SCENE / STYLE: ", 1)[1].split("\n\nLAYOUT ELEMENTS", 1)[0]
    content = CanvasContent(name="FIBO · supplied example", globalPrompt=scene, regions=[CanvasRegion(
        id=f"example-{i+1}", name=f"Region {i+1}", kind="text" if b["metadata"]["type"] == "text" else "object",
        x=b["x"]/1024, y=b["y"]/1024, width=b["width"]/1024, height=b["height"]/1024, order=i,
        description=b["metadata"].get("desc", ""), text=b["metadata"].get("text", ""), palette=b["metadata"].get("palette", [])) for i,b in enumerate(boxes)])
    return {"content": content.model_dump(), "warnings": ["Explicitly loaded supplied FIBO example; review descriptions before generating."]}
