"""Bound local chat payloads without modifying saved conversation/checkpoint data."""
from copy import deepcopy
import json


def fit_payload(payload, context_size, token_count):
    result = deepcopy(payload)
    budget = context_size - int(result.get("max_tokens", 512)) - 256
    if budget <= 0:
        raise ValueError("The local server context is too small for this reply.")
    # Tool results are evidence, not a second copy of the entire workflow catalog.
    for message in result["messages"]:
        if message.get("role") != "tool":
            continue
        try:
            evidence = json.loads(message.get("content", ""))
        except (TypeError, ValueError):
            continue
        if not isinstance(evidence, dict):
            continue
        if isinstance(evidence.get("workflows"), list):
            evidence["workflows"] = [{key: workflow[key] for key in (
                "workflow_id", "id", "name", "score", "capability", "execution_provider",
                "output", "source_kind", "error",
            ) if key in workflow} for workflow in evidence["workflows"] if isinstance(workflow, dict)]
            evidence["context_note"] = "Workflow details omitted; inspect the chosen workflow before use."
        if "graph" in evidence:
            evidence.pop("graph")
            evidence["context_note"] = "Graph omitted; inspection metadata retained."
        contract = evidence.get("recipe_manifest")
        if isinstance(contract, dict) and isinstance(contract.get("fields"), list):
            # Registered inspections repeat the same values in graph, slots,
            # prompt_structure and the manifest. Keep the authoritative roles,
            # values, bounds, readiness and digests once, without losing pairing.
            evidence.pop("slots", None)
            evidence.pop("prompt_structure", None)
            values = {field["slot"]: field.get("value") for field in contract["fields"]
                      if isinstance(field, dict) and isinstance(field.get("slot"), str)}
            package = contract.get("block_party")
            specs = package.get("parameters") if isinstance(package, dict) else []
            for spec in specs if isinstance(specs, list) else []:
                if not isinstance(spec, dict):
                    continue
                slot = f"{spec.get('node_id')}.{spec.get('key')}"
                if slot in values and "default" in spec and spec["default"] == values[slot]:
                    spec.pop("default")  # The identical value is retained in fields.
            evidence["context_note"] = "Duplicate graph/slot/default values omitted; recipe roles, values, parameter bounds and bindings retained."
        message["content"] = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    if token_count(result) <= budget:
        return result
    # Remove oldest background conversation/events, never the explicit request,
    # active production context, character/scene records, or tool-call pairing.
    contexts = []
    for message in result["messages"]:
        if message.get("role") != "user" or not isinstance(message.get("content"), str):
            continue
        try:
            envelope = json.loads(message["content"])
        except ValueError:
            continue
        if not isinstance(envelope, dict):
            continue
        context = envelope.get("context")
        if not isinstance(context, dict):
            continue
        contexts.append((message, envelope, context))
    for key in ("recent_events", "workflow_history", "jobs", "messages"):
        for message, envelope, context in contexts:
            entries = context.get(key)
            floor = 0 if key == "recent_events" else (2 if key in {"workflow_history", "jobs"} else 4)
            while isinstance(entries, list) and len(entries) > floor:
                del entries[:max(1, (len(entries) - floor) // 2)]
                context["context_budget_note"] = "Older background history omitted to fit local context. Ask for missing details; do not invent them."
                message["content"] = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
                if token_count(result) <= budget:
                    return result
    raise ValueError("This request still exceeds the local model context after compacting background history. Use a shorter conversation or reduce attached project context; your message and saved task are retained.")
