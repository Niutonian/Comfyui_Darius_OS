"""Actionable failure categories used by tool results and saved task traces."""


def failure_details(error):
    message = str(error)[:2000]
    text = message.casefold()
    code, recovery, retryable = "workflow_invalid", "correct_arguments", False
    if any(term in text for term in ("timed out", "timeout", "temporarily unavailable", "connection refused", "connection reset", "winerror 10061", "no structured envelope")):
        code, recovery, retryable = "service_unavailable", "retry_after_service_check", True
    elif any(term in text for term in ("another project", "does not belong", "project asset")):
        code, recovery = "reference_scope", "choose_project_references"
    elif any(term in text for term in ("missing model", "not installed", "unknown node", "missing node", "not in list")):
        code, recovery = "dependency_unavailable", "install_dependency_or_choose_workflow"
    elif any(term in text for term in ("unknown workflow", "missing source", "cannot convert")):
        code, recovery = "workflow_unavailable", "refresh_and_inspect_workflow"
    elif any(term in text for term in ("unbound", "image binding", "reference unavailable")):
        code, recovery = "reference_binding", "bind_shot_references"
    elif any(term in text for term in ("quota", "balance", "credentials", "api key")):
        code, recovery = "provider_configuration", "check_provider_settings"
    return {"error": message, "error_code": code, "retryable": retryable, "recovery": recovery}
