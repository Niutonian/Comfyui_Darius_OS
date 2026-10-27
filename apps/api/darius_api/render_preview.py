"""Read-only render evidence from the same slot overrides used at execution."""
import hashlib
import json
import re
from pathlib import Path

from .workflows import resolve_graph_slot


def graph_inputs(graph):
    """Describe connected conditioning, without treating model filenames as prose."""
    if not isinstance(graph, dict) or any(not isinstance(node, dict) for node in graph.values()):
        raise ValueError("Invalid API graph")
    # Ignore disconnected examples, loaders and encoders. Rendering starts at
    # output nodes; only their upstream inputs can affect the saved result.
    from .recipe_adaptation import output_graph
    graph = output_graph(graph)

    def sources(kind):
        pending = [str(value[0]) for node in graph.values() for key, value in node.get("inputs", {}).items()
                   if kind in key.lower() and isinstance(value, list) and len(value) == 2
                   and isinstance(value[1], int) and str(value[0]) in graph]
        visited = set()
        while pending:
            node_id = pending.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            pending.extend(str(value[0]) for value in graph[node_id].get("inputs", {}).values()
                           if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)
                           and str(value[0]) in graph)
        return visited

    positive, negative = sources("positive"), sources("negative")
    # A text generator's instruction channel influences its output, but is not
    # another image description. Follow that channel to its primitive sources.
    system_slots, pending = set(), []
    for node_id, node in graph.items():
        for key, value in node.get("inputs", {}).items():
            instruction = key.lower() in {"system", "system_prompt", "system_message", "developer_prompt", "developer_message"}
            instruction |= key.lower() in {"instruction", "instructions"} and bool(re.search(r"textgenerate|llm|chatcompletion", node.get("class_type", ""), re.I))
            if instruction:
                if isinstance(value, str):
                    system_slots.add(f"{node_id}.{key}")
                elif isinstance(value, list) and len(value) == 2 and str(value[0]) in graph:
                    pending.append(str(value[0]))
    visited = set()
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        node = graph[node_id]
        for key, value in node.get("inputs", {}).items():
            if key not in {"text", "value", "string", "input", "prompt"}:
                continue
            if isinstance(value, str):
                system_slots.add(f"{node_id}.{key}")
            elif isinstance(value, list) and len(value) == 2 and str(value[0]) in graph:
                pending.append(str(value[0]))
    result = {"positive": [], "negative": [], "system": [], "models": [], "image_inputs": []}
    model_keys = {"ckpt_name", "unet_name", "lora_name", "clip_name", "vae_name", "model", "model_name"}
    for node_id, node in graph.items():
        node_type = str(node.get("class_type", ""))
        title = str((node.get("_meta") or {}).get("title", ""))
        for key, value in node.get("inputs", {}).items():
            if not isinstance(value, str):
                continue
            entry = {"slot": f"{node_id}.{key}", "label": title or node_type, "value": value}
            if entry["slot"] in system_slots:
                result["system"].append(entry)
                continue
            if key in model_keys:
                result["models"].append(entry)
            if node_type in {"LoadImage", "LoadImageMask"} and key == "image":
                result["image_inputs"].append(entry)
            text = (bool(re.fullmatch(r"(?:(?:positive|negative)[_.])?(?:prompt|text|script)(?:[_.](?:\d+|l|g|t5|clip))?", key))
                    or (key == "value" and ("string" in node_type.lower() or node_type.lower() == "text")))
            if not text:
                continue
            is_negative = ("negative" in key.lower() or "negative" in title.lower()
                           or (node_id in negative and node_id not in positive))
            if is_negative:
                result["negative"].append(entry)
            elif node_id in positive or not positive:
                result["positive"].append(entry)
    return result


def preview_contract(contract, supplied, request_text=""):
    normalized = contract.validate_inputs(supplied)
    preview = {"workflow_id": contract.id, "workflow_name": contract.name,
               "origin_workflow_id": contract.origin_workflow_id,
               "provider": contract.execution_provider, "verification": "contract",
               "graph_digest": None, "positive": [], "negative": [], "models": [],
               "image_inputs": [], "reference_asset_ids": list(contract.source_asset_ids),
               "warnings": [], "blocked": False, "canvases": []}
    if contract.execution_provider == "local-comfyui" and contract.runtime_mapping.api_format:
        graph = json.loads(Path(contract.workflow_reference).read_text(encoding="utf-8"))
        for field in contract.required_inputs:
            if field.key not in normalized:
                continue
            node_id, key = resolve_graph_slot(graph, field.maps_to.slot)
            graph[node_id]["inputs"][key] = normalized[field.key]
        preview.update(graph_inputs(graph))
        from .recipe_adaptation import LATENTS, output_graph
        preview["canvases"] = [{"node_id": key, "width": node["inputs"]["width"], "height": node["inputs"]["height"]}
            for key, node in output_graph(graph).items() if node.get("class_type") in LATENTS
            and isinstance(node["inputs"].get("width"), int) and isinstance(node["inputs"].get("height"), int)]
        preview["verification"] = "graph"
        preview["graph_digest"] = hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    else:
        # Non-API graphs may require external conversion. Do not execute tools or
        # imply that a contract-only preview verified the final remote graph.
        for field in contract.required_inputs:
            value = normalized.get(field.key)
            if field.type.startswith("asset:") and value:
                preview["reference_asset_ids"].append(value)
            if isinstance(value, str) and ("prompt" in field.key.lower() or field.key in {"script", "text", "positive", "negative"}):
                kind = "negative" if "negative" in field.key.lower() else "positive"
                preview[kind].append({"slot": field.maps_to.slot, "label": field.key, "value": value})
        preview["models"] = [{"slot": "", "label": "Declared model", "value": value} for value in contract.model_dependencies]
        preview["warnings"].append("Contract inputs only; the final provider graph is not available for inspection.")
    def clean(value):
        return " ".join(value.split()).casefold()
    requested = clean(request_text)
    positive = {clean(item["value"]) for item in preview["positive"] if item["value"].strip()}
    negative = {clean(item["value"]) for item in preview["negative"] if item["value"].strip()}
    if positive & negative or (requested and requested in negative):
        preview["warnings"].append("The visual subject is also in negative conditioning. Revise this draft before rendering.")
        preview["blocked"] = True
    if not positive:
        preview["warnings"].append("No readable positive prompt was found. Check the workflow inputs before rendering.")
    elif contract.id.startswith("assistant-") and requested and requested not in positive:
        preview["warnings"].append("The connected positive prompt differs from the creative direction shown in chat.")
    if preview["image_inputs"] and not preview["reference_asset_ids"]:
        preview["warnings"].append("This graph contains saved image inputs with no recorded project reference bindings. Verify that they are intended.")
    preview["reference_asset_ids"] = list(dict.fromkeys(preview["reference_asset_ids"]))
    return preview
