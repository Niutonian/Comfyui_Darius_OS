"""Small deterministic adapters for inspected recipes; never invent graph nodes."""
import math
import re


LATENTS = {"EmptyLatentImage", "EmptySD3LatentImage", "EmptyFlux2LatentImage"}


def links(node):
    return [(field, str(value[0])) for field, value in node.get("inputs", {}).items()
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)]


def output_graph(graph):
    """Resolve only the known boolean switch. Unknown/custom controls stay intact."""
    roots = [key for key, node in graph.items() if node.get("class_type", "").lower().startswith("save")
             or "videocombine" in node.get("class_type", "").lower()]
    if not roots:
        return graph
    active, pending = set(), list(roots)
    while pending:
        key = pending.pop()
        if key in active or key not in graph:
            continue
        active.add(key)
        node = graph[key]
        edges = links(node)
        switch = node.get("inputs", {}).get("switch")
        if node.get("class_type") == "ComfySwitchNode" and isinstance(switch, bool):
            unused = "on_false" if switch else "on_true"
            edges = [(field, target) for field, target in edges if field != unused]
        pending.extend(target for _, target in edges)
    return {key: node for key, node in graph.items() if key in active}


def optional_qwen_loader(graph, loader):
    consumers = [(node, field) for node in graph.values() for field, target in links(node) if target == loader]
    return bool(consumers) and all(node.get("class_type") == "TextEncodeQwenImage21"
        and re.fullmatch(r"images\.image_[1-9]\d*", field) for node, field in consumers)


def bind_references(graph, slots, references):
    """Allow fewer references only for known variable-length Qwen inputs."""
    slots = list(slots)
    if slots and all(optional_qwen_loader(graph, slot.removesuffix(".image")) for slot in slots):
        def position(slot):
            loader = slot.removesuffix(".image")
            return min((key, int(field.removeprefix("images.image_")))
                       for key, node in graph.items() for field, target in links(node)
                       if target == loader and node.get("class_type") == "TextEncodeQwenImage21")
        slots.sort(key=position)
    if len(references) > len(slots):
        raise ValueError("More project references than recipe image inputs.")
    bindings = dict(zip(slots, references))
    for slot in slots[len(references):]:
        loader = slot.removesuffix(".image")
        if not optional_qwen_loader(graph, loader):
            raise ValueError("A required recipe image input has no project reference.")
    return bindings


def adapt_references(graph, bindings, schemas):
    """Remove unused autogrow references only when the LIVE schema permits it."""
    removals = []
    for key, node in graph.items():
        if node.get("class_type") != "TextEncodeQwenImage21":
            continue
        inputs = node["inputs"]
        fields = [field for field in inputs if re.fullmatch(r"images\.image_[1-9]\d*", field)]
        unused = [field for field in fields if isinstance(inputs[field], list)
                  and f"{inputs[field][0]}.image" not in bindings
                  and optional_qwen_loader(graph, str(inputs[field][0]))]
        if not unused:
            continue
        spec = next((section["images"] for section in schemas.get(node["class_type"], {}).get("input", {}).values()
                     if isinstance(section, dict) and "images" in section), None)
        template = spec[1].get("template", {}) if isinstance(spec, list) and len(spec) > 1 and spec[0] == "COMFY_AUTOGROW_V3" else {}
        names, minimum = template.get("names"), template.get("min")
        if not isinstance(names, list) or not isinstance(minimum, int) or len(fields) - len(unused) < minimum:
            raise ValueError("The installed Qwen schema does not confirm these reference inputs are optional.")
        if any(field.removeprefix("images.") not in names for field in fields):
            raise ValueError("Qwen reference names differ from the installed schema. Refresh the recipe.")
        # Removing a tail keeps the installed autogrow order contiguous.
        ordered = ["images." + name for name in names if "images." + name in inputs]
        if ordered[:len(ordered) - len(unused)] != [field for field in ordered if field not in unused]:
            raise ValueError("Bind Qwen references in their declared order; an interior slot cannot be omitted.")
        removals.extend((key, field) for field in unused)
    removed_loaders = {str(graph[key]["inputs"][field][0]) for key, field in removals}
    for key, field in removals:
        del graph[key]["inputs"][field]
    # Drop the known switch's inactive optional arm, not arbitrary disconnected
    # recipe nodes. In particular, retain sampler controls and seed mappings.
    prepared = {key: {**node, "inputs": {field: value for field, value in node["inputs"].items()
                                   if not (node.get("class_type") == "ComfySwitchNode"
                                           and isinstance(node["inputs"].get("switch"), bool)
                                           and field == ("on_false" if node["inputs"]["switch"] else "on_true"))}}
            for key, node in graph.items()}
    consumed = {target for node in prepared.values() for _, target in links(node)}
    return {key: node for key, node in prepared.items()
            if not (key in removed_loaders and node.get("class_type") in {"LoadImage", "LoadImageMask"}
                    and key not in consumed and f"{key}.image" not in bindings)}


def requested_canvas(text):
    dimensions = re.findall(r"\b(\d{3,4})\s*[x×]\s*(\d{3,4})\b", text, re.I)
    ratios = re.findall(r"(?<![\w:])(\d{1,2})\s*:\s*(\d{1,2})(?![\d:])", text)
    if dimensions:
        width, height = map(int, dimensions[-1])
        if min(width, height) < 256 or max(width, height) > 4096 or width * height > 4194304 or width % 16 or height % 16:
            raise ValueError("Use a canvas aligned to 16 pixels, 256–4096 pixels per side, up to 4 megapixels.")
        if ratios and not math.isclose(width / height, int(ratios[-1][0]) / max(1, int(ratios[-1][1])), rel_tol=.015):
            raise ValueError("The requested dimensions and aspect ratio disagree. Choose one canvas.")
        return width, height
    if not ratios:
        return None
    a, b = map(int, ratios[-1])
    if not a or not b or not .25 <= a / b <= 4:
        raise ValueError("Choose an image aspect ratio between 1:4 and 4:1.")
    divisor = math.gcd(a, b)
    a, b = a // divisor, b // divisor
    unit = math.lcm(16 // math.gcd(a, 16), 16 // math.gcd(b, 16))
    multiple = max(unit, round(math.sqrt(1024 * 1024 / (a * b)) / unit) * unit)
    return a * multiple, b * multiple


def apply_canvas(graph, text):
    canvas = requested_canvas(text)
    if not canvas:
        return None
    # Qwen's output 2 is a reference-sized latent; select the EXISTING empty
    # canvas branch rather than silently retaining the reference aspect ratio.
    for node in output_graph(graph).values():
        if node.get("class_type") != "ComfySwitchNode":
            continue
        inputs = node["inputs"]
        arms = {field: graph.get(str(inputs[field][0]), {}) for field in ("on_true", "on_false")
                if isinstance(inputs.get(field), list) and len(inputs[field]) == 2}
        latent = [field for field, arm in arms.items() if arm.get("class_type") in LATENTS]
        qwen = [field for field, arm in arms.items() if arm.get("class_type") == "TextEncodeQwenImage21"
                and inputs[field][1] == 2]
        if len(latent) == len(qwen) == 1 and isinstance(inputs.get("switch"), bool):
            inputs["switch"] = latent[0] == "on_true"
    targets = [node for node in output_graph(graph).values() if node.get("class_type") in LATENTS]
    if len(targets) != 1:
        raise ValueError("This recipe has no single verified image canvas. Configure its aspect ratio in the base workflow before rendering.")
    targets[0]["inputs"].update(width=canvas[0], height=canvas[1])
    return canvas
