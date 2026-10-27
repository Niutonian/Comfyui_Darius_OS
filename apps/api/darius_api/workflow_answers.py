"""Read-only workflow-list receipts, without another model/tool round trip."""
import re

from .media_intent import is_information_request


def catalog_answer(body, request_text):
    if (not is_information_request(request_text) or not re.search(r"\bworkflows?\b", request_text, re.I)
            or not re.search(r"\b(list|show|available|which|what)\b", request_text, re.I)
            or re.search(r"\b(compare|recommend|best|why|explain|how)\b", request_text, re.I)):
        return None
    from .workflow_executor import tool_history, final_response
    history = tool_history(body)
    latest = next((result for operation, _, result in reversed(history)
        if operation in {"list_workflows", "discover_workflows"} and not result.get("error")), None)
    if not isinstance(latest, dict) or not isinstance(latest.get("workflows"), list):
        return None
    names = []
    for entry in latest["workflows"][:100]:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("workflow_id") or entry.get("id") or entry.get("path")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        name = re.sub(r"\.json$", "", name, flags=re.I)
        name = re.sub(r"[\x00-\x1f]", " ", name).strip()[:160]
        capability = entry.get("capability")
        label = name + (f" — {capability}" if isinstance(capability, str) and len(capability) < 60 else "")
        if label and label not in names:
            names.append(label)
    if names:
        reply = f"The catalog returned {len(names)} workflow{'s' if len(names) != 1 else ''}:\n\n" + "\n".join("- " + name for name in names)
        limit = latest.get("limit")
        if isinstance(limit, int) and limit > 0 and len(latest["workflows"]) >= limit:
            reply += "\n\nThis is a limited catalog page; ask for a workflow name or a more specific filter to narrow it down."
    else:
        reply = "The catalog returned no matching workflows. Try a different workflow name or refresh Trusted workflows."
    return final_response(reply, state="replied")
