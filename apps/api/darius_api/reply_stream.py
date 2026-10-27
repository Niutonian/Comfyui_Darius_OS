"""Request-local reply streaming; tool replies remain verified before publication."""
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar

_sink = ContextVar("reply_stream_sink", default=None)


@contextmanager
def reply_stream(sink):
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def streaming():
    return _sink.get() is not None


def publish(text):
    sink = _sink.get()
    if sink and text:
        sink({"type": "delta", "text": text})


def conversational(text, metadata, messages):
    """Conservative allowlist: ambiguity and resumed tasks retain the tool path."""
    if metadata.get("asset_ids") or metadata.get("preferred_workflow_id") or metadata.get("task"):
        return False
    if re.search(r"\b(workflow|comfy\w*|render\w*|generat\w*|animat\w*|image|picture|photo|video|asset|file|model|node|seed|job|status|rename|delete|save|update|create|record|scene|shot|character|change|edit|remove|add|queue|run|start|stop|cancel|pause|resume|inspect|check|list|find|search|that|this|these|those|it|them)\b", text, re.I):
        return False
    if re.fullmatch(r"\s*(?:hi|hello|hey|thanks|thank you|good morning)(?:\s+(?:mate|buddy|darius|bro))?[.!?\s]*", text, re.I):
        return True
    return bool(re.match(r"^\s*(?:explain\b|tell me about\b|why\b|what is\b|what are\b|how does\b|help me brainstorm\b|brainstorm\b|write (?:a |an )?(?:poem|story|logline|dialogue)\b)", text, re.I))


def read_events(response, chat=False):
    """Read SSE, rejecting truncated output rather than persisting partial answers."""
    parts, data, response_id, complete = [], [], None, False
    def event(raw):
        nonlocal response_id, complete
        if raw == "[DONE]":
            complete = True
            return
        item = json.loads(raw)
        if chat:
            response_id = item.get("id", response_id)
            for choice in item.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("tool_calls"):
                    raise ValueError("Unexpected tool call in conversational reply")
                text = delta.get("content") or ""
                if choice.get("finish_reason") in {"length", "content_filter"}:
                    raise ValueError("The reply was incomplete; retry the saved message")
                if text:
                    parts.append(text)
                    publish(text)
        else:
            kind = item.get("type")
            if kind == "response.output_text.delta":
                text = item.get("delta", "")
                parts.append(text)
                publish(text)
            elif kind == "response.completed":
                response_id = item.get("response", {}).get("id")
                complete = True
            elif kind in {"error", "response.failed", "response.incomplete"}:
                raise ValueError("The AI could not complete this reply; retry the saved message")
    for line in response:
        line = line.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                event("\n".join(data))
                data = []
            if complete:
                break
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        event("\n".join(data))
    if not complete or not parts:
        raise ValueError("The AI reply stream was interrupted; retry the saved message")
    return {"id": response_id, "output": [{"type": "message", "content": [{"type": "output_text", "text": "".join(parts)}]}]}
