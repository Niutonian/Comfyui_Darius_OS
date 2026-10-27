"""Checks applied to API-format graphs before they reach ComfyUI MCP."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from urllib.parse import urlparse
from pathlib import PurePosixPath
from typing import Any

IMAGE_NODES = {"LoadImage", "LoadImageMask"}


def normalize_dynamic_inputs(graph: dict[str, Any], schemas: dict[str, Any]) -> list[str]:
    """Check autogrow names against the live schema, repairing one known alias.

    Qwen drafts sometimes number images as image0/image1. ComfyUI accepts
    those through validation but forwards them as unexpected Python arguments.
    Repair only a complete zero-based sequence; never guess mixed references.
    """
    changes = []
    for node_id, node in graph.items():
        inputs = node["inputs"]
        schema = schemas.get(node.get("class_type"), {})
        for section in ("required", "optional"):
            for field, spec in schema.get("input", {}).get(section, {}).items():
                if not isinstance(spec, list) or len(spec) < 2 or spec[0] != "COMFY_AUTOGROW_V3":
                    continue
                names = spec[1].get("template", {}).get("names")
                if not isinstance(names, list) or not names:
                    continue
                prefix = field + "."
                keys = [key for key in inputs if key.startswith(prefix)]
                allowed = {prefix + name for name in names}
                invalid = [key for key in keys if key not in allowed]
                if not invalid:
                    continue
                aliases = sorted(keys, key=lambda key: int(key[len(prefix) + 5:])
                                 if re.fullmatch(re.escape(prefix) + r"image\d+", key) else -1)
                expected = [prefix + f"image{i}" for i in range(len(keys))]
                if (node.get("class_type") == "TextEncodeQwenImage21" and field == "images"
                        and field not in inputs and aliases == expected and len(keys) <= len(names)
                        and names[:len(keys)] == [f"image_{i + 1}" for i in range(len(keys))]):
                    values = [inputs.pop(key) for key in aliases]
                    for name, value in zip(names, values):
                        inputs[prefix + name] = value
                    changes.append(f"{node_id}: normalized Qwen image slots to {', '.join(names[:len(keys)])}")
                else:
                    raise _error(
                        f"Comfy preflight: {node_id} has unsupported dynamic inputs {', '.join(invalid)}; "
                        f"use the installed {field} slots: {', '.join(sorted(allowed))}. "
                        "Preserve the reference order and inspect_node before preparing again."
                    )
    return changes


def validate_capability_graph(graph: dict[str, Any], capability: str) -> None:
    """Reject known graph/capability mismatches before ComfyUI execution."""
    if capability == "text-to-video":
        for node_id, node in graph.items():
            if isinstance(node, dict) and node.get("class_type") == "H3Keyframes":
                raise _error(
                    "Comfy preflight: text-to-video graph uses H3Keyframes, which requires an image; "
                    "use the H3 text-to-video node (t2va) or declare image-to-video"
                )


def _error(message: str) -> Exception:
    # Lazy import avoids a providers -> preflight -> providers import cycle.
    from .providers import ProviderError
    return ProviderError(message)


def _image_reference(value: Any, slot: str) -> tuple[str, str, str]:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"Comfy preflight: {slot}.image is empty")
    value = value.strip().replace("\\", "/")
    if value.startswith("__") and value.endswith("__"):
        raise _error(f"Comfy preflight: {slot}.image is unresolved ({value}); bind a project image before queueing")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise _error(f"Comfy preflight: {slot}.image is not a safe Comfy input path")
    if not path.name:
        raise _error(f"Comfy preflight: {slot}.image has no filename")
    subfolder = "/".join(path.parts[:-1])
    return value, path.name, subfolder


def _visible_in_comfy(base_url: str, filename: str, subfolder: str) -> None:
    from .providers import ProviderError

    query = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": "input"})
    url = f"{base_url.rstrip('/')}/view?{query}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                response.read(1)
            return
        except urllib.error.HTTPError as exc:
            if exc.code not in {408, 429, 502, 503, 504}:
                raise _error(
                    f"Comfy preflight: image {filename!r} is not visible in input storage "
                    f"(HTTP {exc.code}); upload and bind the project image again"
                ) from exc
            failure = exc
        except (OSError, TimeoutError, ValueError) as exc:
            failure = exc
        if attempt < 2:
            time.sleep(0.25 * (attempt + 1))
    raise _error(
        f"Comfy preflight: could not verify image {filename!r} after 3 attempts "
        f"({type(failure).__name__}); check ComfyUI availability before retrying"
    ) from failure


def validate_graph(graph: dict[str, Any], *, comfy_base_url: str, verify_images: bool = True) -> dict[str, Any]:
    """Validate values that the MCP validator cannot safely repair.

    Returns a normalized copy so Windows paths cannot leak into an API graph.
    """
    if not isinstance(graph, dict) or not graph:
        raise _error("Comfy preflight: graph is empty")
    normalized = json.loads(json.dumps(graph))
    for node_id, node in normalized.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            raise _error(f"Comfy preflight: node {node_id} is malformed")
        if node.get("class_type") not in IMAGE_NODES or "image" not in node["inputs"]:
            continue
        value, filename, subfolder = _image_reference(node["inputs"]["image"], f"{node_id}")
        node["inputs"]["image"] = value
        if verify_images:
            _visible_in_comfy(comfy_base_url, filename, subfolder)
    return normalized


def validation_message(validation: dict[str, Any]) -> str:
    errors = validation.get("errors") if isinstance(validation, dict) else None
    if isinstance(errors, dict):
        errors = [f"{key}: {value}" for key, value in errors.items()]
    if isinstance(errors, list) and errors:
        detail = "; ".join(str(item) for item in errors[:8])
        return f"Comfy workflow validation failed: {detail}"
    return "Comfy workflow validation failed before rendering"


def accept_zero_reference_qwen_warning(
    validation: dict[str, Any], graph: dict[str, Any], comfy_base_url: str, *, node_type="TextEncodeQwenImage21"
) -> dict[str, Any]:
    """Filter the CLI's false positive for Qwen's optional zero-slot image input.

    The CLI validator currently treats the required-section placement of this
    autogrow input as mandatory even though ComfyUI declares template.min=0.
    Only waive that exact warning after checking the live local node schema.
    """
    if node_type not in {"TextEncodeQwenImage21", "TextEncodeFibo2"}:
        return validation
    qwen_nodes = {
        str(node_id)
        for node_id, node in graph.items()
        if isinstance(node, dict)
        and node.get("class_type") == node_type
        and isinstance(node.get("inputs"), dict)
        and "images" not in node["inputs"]
    }
    if not qwen_nodes:
        return validation

    endpoint = urlparse(comfy_base_url)
    if (endpoint.scheme != "http" or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}
            or endpoint.username or endpoint.password):
        return validation
    try:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(f"{comfy_base_url.rstrip('/')}/object_info/{node_type}", timeout=3) as response:
            metadata = json.loads(response.read().decode("utf-8"))
        schema = metadata[node_type]
        image_spec = schema["input"]["required"]["images"]
        if (not isinstance(image_spec, list) or len(image_spec) < 2
                or image_spec[0] != "COMFY_AUTOGROW_V3"
                or image_spec[1].get("template", {}).get("min") != 0
                or schema.get("api_node")):
            return validation
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return validation

    result = dict(validation)
    errors = validation.get("errors")
    if not isinstance(errors, list):
        return validation
    retained = [
        error
        for error in errors
        if not (
            isinstance(error, dict)
            and error.get("code") == "autogrow_no_slots"
            and error.get("field") == "images"
            and str(error.get("node_id")) in qwen_nodes
        )
    ]
    if len(retained) == len(errors):
        return validation
    result["errors"] = retained
    result["valid"] = not retained
    if "error_count" in result:
        result["error_count"] = len(retained)
    return result
