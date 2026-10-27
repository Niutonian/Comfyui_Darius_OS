"""Small, provider-neutral tool argument boundary; never guess workflow wiring."""
import json


def parse_arguments(request):
    value = request.get("arguments", request.get("arguments_json", "{}"))
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("```") and value.endswith("```"):
            value = value.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as exc:
            raise ValueError("arguments_json must contain one valid JSON object. Fix JSON syntax and retry this tool.") from exc
    if not isinstance(value, dict):
        raise ValueError("Tool arguments must be a JSON object, not an array or string.")
    args = dict(value)
    operation = request.get("operation")
    required = {
        "asset_details": ["asset_id"], "rename_asset": ["asset_id", "name"],
        "upload_asset": ["asset_id"], "inspect_workflow": ["workflow_id"],
        "prepare_workflow": ["workflow_id", "name"], "queue_local_render": ["workflow_id"],
        "job_status": ["job_id"], "inspect_node": ["name"], "search_nodes": ["query"],
        "prepare_graph": ["name"],
    }
    for key in required.get(operation, []):
        if not isinstance(args.get(key), str) or not args[key].strip():
            raise ValueError(f"{operation}: {key} must be a nonempty string.")
    for key in ("limit", "offset"):
        if key in args:
            value = args[key]
            if isinstance(value, str) and value.isdecimal():
                value = int(value)
            if type(value) is not int or value < (1 if key == "limit" else 0):
                raise ValueError(f"{key} must be a {'positive' if key == 'limit' else 'nonnegative'} integer.")
            args[key] = min(value, 100) if key == "limit" else value
    for key in ("overrides", "asset_bindings"):
        if key in args and not isinstance(args[key], dict):
            raise ValueError(f"{key} must be an object keyed by inspected workflow slots.")
    if operation in {"prepare_graph", "validate_graph"} and not isinstance(args.get("graph"), dict):
        raise ValueError("graph must be an API-format object. Inspect a saved workflow before preparing it.")
    if "seed_mode" in args and args["seed_mode"] not in ("randomize", "preserve"):
        raise ValueError("seed_mode must be randomize or preserve.")
    if "output_kind" in args and args["output_kind"] not in ("image", "video", "audio"):
        raise ValueError("output_kind must be image, video, or audio.")
    if operation == "view_assets":
        ids = args.get("asset_ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 4 or any(not isinstance(i, str) for i in ids):
            raise ValueError("asset_ids must be a list of 1–4 active-project image IDs.")
    if operation == "present_assets":
        if not isinstance(args.get("action", "open"), str) or args.get("action", "open") not in {"open", "close", "next", "previous"}:
            raise ValueError("Viewer action must be open, close, next, or previous.")
        ids = args.get("asset_ids", [])
        if not isinstance(ids, list) or len(ids) > 12 or any(not isinstance(key, str) for key in ids):
            raise ValueError("asset_ids must list at most twelve project asset IDs.")
    return args
