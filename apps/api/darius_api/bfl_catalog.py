"""FLUX 3 contracts from BFL's public schema, checked 2026-10-08."""
import base64
import json
import math
import re
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMAS = json.loads(Path(__file__).with_name("bfl-schema.json").read_text())["schemas"]
MODELS = {
    "bfl-flux-3-image": ("FLUX 3 Image", "flux-3-image", "Flux3ImageInputs", "text-to-image"),
    "bfl-flux-3-image-edit": ("FLUX 3 Image · Edit / combine references", "flux-3-image", "Flux3ImageInputs", "image-to-image"),
    "bfl-flux-3-text-to-video": ("FLUX 3 · Text to video", "flux-3-video", "Flux3VideoT2VInputs", "text-to-video"),
    "bfl-flux-3-image-to-video": ("FLUX 3 · Keyframes to video", "flux-3-video", "Flux3VideoI2VInputs", "image-to-video"),
    "bfl-flux-3-video-continuation": ("FLUX 3 · Continue video", "flux-3-video", "Flux3VideoV2VInputs", "video-to-video"),
    "bfl-flux-3-draft-enhance": ("FLUX 3 · Enhance saved draft", "flux-3-video", "Flux3VideoDraftEnhanceInputs", "video-to-video"),
    "bfl-flux-3-video-edit": ("FLUX Video Edit [fast]", "flux-tools/video-edit-v1", "Flux3VideoVE2VNamedInputs", "video-to-video"),
    "bfl-flux-3-video-upscale": ("FLUX Video Upscale · Precise / creative", "flux-tools/video-upscale-v1", "Flux3VideoUpscaleInputs", "video-to-video"),
}
MEDIA_FIELDS = {"images": "image", "keyframes": "image", "start_video": "video", "video": "video", "input_video": "video", "draft_cache": "video"}


def field_options(schema):
    if "const" in schema:
        return [schema["const"]]
    if "enum" in schema:
        return schema["enum"]
    if "anyOf" in schema:
        result = []
        for part in schema["anyOf"]:
            result.extend(field_options(part))
            if part.get("type") == "integer" and "maximum" in part and "minimum" in part:
                result.extend(range(int(part["minimum"]), int(part["maximum"]) + 1))
        return list(dict.fromkeys(result))
    return []


def contracts():
    from .workflows import WorkflowContract
    result = []
    for identifier, (name, endpoint, schema_name, capability) in MODELS.items():
        schema = SCHEMAS[schema_name]
        fields = []
        for key, field in schema["properties"].items():
            if key in {"webhook_url", "webhook_secret"}:
                continue  # Darius durably polls jobs instead of accepting callbacks.
            field_type = field.get("type", "json")
            if key in {"start_video", "video", "input_video", "draft_cache"}:
                field_type = "asset:video"
            fields.append({"key": key, "type": field_type, "required": key in schema.get("required", []) or (capability == "image-to-image" and key == "images"),
                "default": field.get("default", field.get("const")), "description": field.get("description", ""),
                "minimum": field.get("minimum"), "maximum": field.get("maximum"), "maps_to": {"slot": key}})
        result.append(WorkflowContract.model_validate({"id": identifier, "name": name, "version": "2026-10-08", "execution_provider": "bfl",
            "workflow_reference": endpoint, "capability": capability, "required_inputs": fields,
            "runtime_mapping": {"filename_prefix_slot": "unused", "api_format": False}, "output": {"kind": "image" if capability in {"text-to-image", "image-to-image"} else "video", "count": 1},
            "model_dependencies": [name], "requires_approval": True}))
    return result


def validate_inputs(identifier, inputs):
    schema = SCHEMAS[MODELS[identifier][2]]
    errors = list(Draft202012Validator(schema).iter_errors(inputs))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "parameters"
        # ValidationError.message can contain full base64 media or user secrets.
        raise ValueError(f"Invalid FLUX parameter {location} ({error.validator}); check the field's documented limits.")
    if identifier == "bfl-flux-3-image-edit" and not inputs.get("images"):
        raise ValueError("Image editing requires at least one reference image")
    for key in ("images", "keyframes"):
        value = inputs.get(key)
        if isinstance(value, list):
            timed = key == "keyframes" and value and isinstance(value[0], list)
            pairs = value if timed else []
            if key == "keyframes" and len(value) == 2 and isinstance(value[0], (int, float)):
                pairs, value = [value], [value]
            if not 1 <= len(value) <= 10:
                raise ValueError(f"{key} supports 1–10 references")
            if pairs:
                times = [pair[0] for pair in pairs]
                duration = inputs.get("duration", "auto")
                if any(not math.isfinite(t) or t < 0 or t > 20 for t in times) or any(a >= b for a, b in zip(times, times[1:])) or (isinstance(duration, int) and times[-1] > duration):
                    raise ValueError("Keyframe times must be increasing and within the clip duration")
            elif key == "keyframes" and len(value) > 2 and inputs.get("duration", "auto") == "auto":
                raise ValueError("Three or more untimed keyframes require an explicit duration")


def reference_ids(inputs):
    result = []
    def walk(value):
        if isinstance(value, str) and (value.startswith("asset:") or re.fullmatch(r"[0-9a-fA-F-]{36}", value)):
            result.append(value.removeprefix("asset:"))
        elif isinstance(value, list):
            for item in value:
                walk(item)
    for key in MEDIA_FIELDS:
        value = inputs.get(key)
        walk(value)
    return list(dict.fromkeys(result))


def resolve_media(session, project_id, inputs, settings=None, *, encode=False):
    from .database import Asset
    values = json.loads(json.dumps(inputs))
    def resolve(value, kind, draft=False):
        if isinstance(value, list):
            return [resolve(item, kind, draft) for item in value]
        if not isinstance(value, str):
            return value
        if not value.startswith("asset:") and not re.fullmatch(r"[0-9a-fA-F-]{36}", value):
            return value
        identifier = value.removeprefix("asset:")
        asset = session.get(Asset, identifier)
        if not asset:
            if value.startswith("asset:") or re.fullmatch(r"[0-9a-fA-F-]{36}", value):
                raise ValueError("A referenced project asset no longer exists")
            return value  # Explicit API URL/base64 input; sent to BFL only after approval.
        if asset.project_id != project_id or asset.kind != kind:
            raise ValueError("FLUX references must belong to the active project and match the required media type")
        path = Path(asset.metadata_json.get("bfl_draft_cache_path", "")) if draft else Path(asset.path)
        if not path.is_file() or (settings and not path.resolve().is_relative_to(settings.data_dir.resolve())):
            raise ValueError("The referenced media or saved draft cache is unavailable")
        if path.stat().st_size > min(settings.max_upload_bytes if settings else 50 * 1024 * 1024, 50 * 1024 * 1024):
            raise ValueError("FLUX reference exceeds the 50 MB upload limit")
        if not encode:
            return value
        content = base64.b64encode(path.read_bytes()).decode("ascii")
        return content if draft else f"data:{asset.mime_type};base64,{content}"
    for key, kind in MEDIA_FIELDS.items():
        if key in values:
            values[key] = resolve(values[key], kind, key == "draft_cache")
    return values


def estimate(identifier, inputs):
    mode = inputs.get("mode")
    duration = inputs.get("duration")
    if mode not in {"t2v", "i2v", "v2v"} or not isinstance(duration, int):
        return None
    if inputs.get("draft"):
        rate = 0.12 if mode == "v2v" else 0.06
    else:
        rates = {"hd": .41, "fhd": .53, "qhd": .65, "uhd": .95} if mode == "v2v" else {"hd": .17, "fhd": .29, "qhd": .40, "uhd": .80}
        rate = rates[inputs.get("resolution", "hd")]
    return round(rate * duration, 2)
