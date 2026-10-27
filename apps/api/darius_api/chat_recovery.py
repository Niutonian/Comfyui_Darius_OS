"""Small recovery contract shared by preflight, executor and chat presentation."""
from .workflow_errors import failure_details


def recovery_for(reason, code=None, *, has_jobs=False):
    details = failure_details(reason)
    code = code or details["error_code"]
    if code in {"subject_selection_required", "reference_selection_required", "missing_recipe_references", "missing_shot_references", "reference_binding", "reference_scope", "incompatible_recipe_references", "invalid_execution_intent"}:
        action, label = "clarify", "Choose or attach the reference"
    elif code in {"recipe_mapping_required", "prompt_mapping_required", "workflow_unavailable", "workflow_selection_required", "workflow_incompatible", "unbound_video_inputs", "dependency_unavailable", "ambiguous_recipe_setting"}:
        action, label = "workflows", "Open trusted workflows"
    elif code == "provider_configuration":
        action, label = "settings", "Open settings"
    elif code == "service_unavailable":
        action, label = "retry", "Retry saved request"
    else:
        action, label = "retry", "Retry saved request"
    if has_jobs:
        action, label = "jobs", "Check existing renders"
    return {"version": 1, "code": code, "action": action, "label": label,
            "can_retry": not has_jobs and action != "clarify", "detail": str(reason)[:2000]}


def preflight_code(reason):
    text = str(reason).casefold()
    if "between one and six" in text:
        return "invalid_execution_intent"
    if any(term in text for term in ("attach", "specific image", "previous result", "could not identify", "several outputs", "referenced render", "referenced image")):
        return "reference_selection_required"
    if any(word in text for word in ("image", "reference", "several outputs")) and not any(word in text for word in ("base recipe", "workflow", "text-to-video recipe")):
        return "reference_selection_required"
    return "workflow_selection_required"
