"""Generation identity independent of template filenames and default seeds."""
import re
import secrets


def prepare_seeds(graph, mode="randomize"):
    if mode not in {"randomize", "preserve"}:
        raise ValueError("seed_mode must be randomize or preserve")
    seeds = {}
    for node_id, node in graph.items():
        for field in ("seed", "noise_seed"):
            value = node.get("inputs", {}).get(field)
            target, key = node, field
            if isinstance(value, list) and len(value) == 2:
                target = graph.get(str(value[0]), {})
                if target.get("class_type") != "PrimitiveInt":
                    continue
                key = "value"
                value = target.get("inputs", {}).get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                if mode == "randomize":
                    target["inputs"][key] = secrets.randbelow(2**32)
                seeds[f"{node_id}.{field}"] = target["inputs"][key]
    return seeds


def input_seeds(contract, inputs):
    seeds = {item.maps_to.slot: inputs[item.key] for item in contract.required_inputs
            if item.maps_to.slot.rsplit(".", 1)[-1] in {"seed", "noise_seed"}
            and isinstance(inputs.get(item.key), int) and not isinstance(inputs[item.key], bool)}
    if contract.runtime_mapping.api_format:
        import json
        from pathlib import Path
        from .workflows import resolve_graph_slot
        graph = json.loads(Path(contract.workflow_reference).read_text(encoding="utf-8"))
        for item in contract.required_inputs:
            if item.key in inputs:
                node_id, field = resolve_graph_slot(graph, item.maps_to.slot)
                graph[node_id]["inputs"][field] = inputs[item.key]
        seeds.update(prepare_seeds(graph, "preserve"))
    return seeds


def output_name(prompt, job_id, index, suffix):
    words = re.findall(r"[^\W_]+", prompt.lower(), flags=re.UNICODE)
    slug = "-".join(words[:10])[:90].strip("-") or "generation"
    return f"{slug}-{job_id[:8]}-{index:02d}{suffix}"
