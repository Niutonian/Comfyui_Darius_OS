"""Native Ollama transport with per-model budgets; no cloud-provider policy."""
from __future__ import annotations

from copy import deepcopy
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from uuid import uuid4

from .diagnostics import record, redact
from .llama_context import fit_payload
from .providers import ProviderError

_metadata_cache = {}


def local_opener():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def metadata(settings, model):
    endpoint = urlparse(settings.ollama_base_url)
    if (endpoint.scheme != "http" or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ProviderError("OLLAMA_BASE_URL must point to a loopback server.")
    key = (settings.ollama_base_url, model)
    cached_at, cached = _metadata_cache.get(key, (0, None))
    if cached is not None and time.monotonic() - cached_at < 300:
        return cached
    request = urllib.request.Request(settings.ollama_base_url + "/api/show",
        data=json.dumps({"model": model}).encode(), headers={"Content-Type": "application/json"})
    try:
        with local_opener().open(request, timeout=5) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Model metadata exceeded its safety limit")
        result = json.loads(raw)
        if not isinstance(result, dict) or not isinstance(result.get("model_info"), dict):
            raise ValueError("Invalid model metadata")
    except (OSError, ValueError) as exc:
        record(settings, "ollama", "error", "model_metadata_failed", model=model, error_type=type(exc).__name__)
        raise ProviderError(f"Could not inspect Ollama model {model}. Check that it is installed and Ollama is running, then refresh the model list. Your saved task is retained.") from exc
    _metadata_cache[key] = (time.monotonic(), result)
    return result


def profile(settings, model, details, *, conversational=False):
    ornith = "ornith" in model.lower()
    context = 32768 if ornith else settings.ollama_context_tokens
    try:
        overrides = json.loads(settings.ollama_model_contexts or "{}")
        if not isinstance(overrides, dict):
            raise ValueError()
        context = overrides.get(model, context)
        if isinstance(context, bool) or not isinstance(context, int) or not 2048 <= context <= 262144:
            raise ValueError()
    except (ValueError, TypeError):
        raise ProviderError("OLLAMA_MODEL_CONTEXTS must be a JSON object mapping model names to context sizes between 2048 and 262144 tokens.") from None
    limits = [value for key, value in details.get("model_info", {}).items()
              if key.endswith(".context_length") and isinstance(value, int) and not isinstance(value, bool) and value > 0]
    if limits:
        context = min(context, min(limits))
    if context < 2048:
        raise ProviderError(f"Ollama model {model} has too little context for Darius. Choose a model with at least 2048 tokens.")
    # Reserve generation space instead of allowing thinking to consume the input window.
    output = min(2048 if conversational else (8192 if ornith else 4096), max(256, context // 4))
    settings_for_turn = {"num_ctx": context, "num_predict": output}
    if ornith:
        settings_for_turn.update(temperature=1.0 if conversational else 0.6,
            top_p=0.95, top_k=20, min_p=0.0, presence_penalty=1.5 if conversational else 0.0, repeat_penalty=1.0)
    result = {"options": settings_for_turn, "keep_alive": "5m"}
    capabilities = details.get("capabilities") or []
    if not isinstance(capabilities, list):
        raise ProviderError("Ollama returned invalid model capabilities. Refresh the model list and retry.")
    if "thinking" in capabilities:
        result["think"] = bool(ornith and not conversational)
    return result


def estimate_input(payload):
    """Conservative UTF-8 byte bound, NOT an exact tokenizer count.

    Ollama exposes no public template/tokenize endpoint. Count textual UTF-8
    bytes plus template headroom, and reserve 8192 tokens per attached image.
    Never count the base64 representation as textual conversation history.
    """
    # Count the text the template receives, not JSON wire escaping of that
    # text. Serializing an already-JSON context again inflated the old bound.
    def size(value):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return len(text.encode("utf-8"))
    total = 512
    for message in payload.get("messages", []):
        total += 64 + size(message.get("content", ""))
        total += len(message.get("images", [])) * 8192
        for call in message.get("tool_calls", []):
            function = call.get("function") or {}
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    pass
            total += 128 + size(function.get("name", "")) + size(arguments)
    if payload.get("tools"):
        total += size(payload["tools"]) + 256 * len(payload["tools"])
    if payload.get("response_format"):
        total += size(payload["response_format"])
    return total


def budget(payload, context_size):
    candidate = deepcopy(payload)
    output = int(candidate.get("max_tokens", 512))
    # Preserve input by reducing an optional large reasoning allowance before
    # rejecting an otherwise usable small-context turn. Never reduce below 2K
    # when the requested allowance is at least that large.
    reservations = list(dict.fromkeys([output, min(output, 4096), min(output, 2048)]))
    for reserve in reservations:
        candidate["max_tokens"] = reserve
        try:
            return fit_payload(candidate, context_size, estimate_input)
        except ValueError:
            continue
    raise ProviderError(f"Darius could not verify that this request fits Ollama's conservative context budget ({context_size:,} tokens configured, {reservations[-1]:,} reserved for the reply). This estimate is not an actual token count. Reduce background project context or adjust this model's profile; your current message and saved task are retained.")


def native_messages(messages):
    prepared = deepcopy(messages)
    names = {}
    for message in prepared:
        for call in message.get("tool_calls", []):
            function = call.get("function", {})
            raw = function.get("arguments", {})
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    raw = {"_invalid_json_arguments": raw, "_history_note": "Previous malformed call was rejected, not executed."}
            if not isinstance(raw, dict):
                raise ProviderError("Saved Ollama tool arguments are invalid. Your task is retained; prepare a fresh request.")
            function["arguments"] = raw
            if isinstance(call.get("id"), str):
                names[call["id"]] = function.get("name")
        if message.get("role") == "tool" and names.get(message.get("tool_call_id")):
            message["tool_name"] = names[message["tool_call_id"]]
    return prepared


def read_native(response, *, streamed):
    from .reply_stream import publish
    parts, calls, final = [], [], None
    items = (json.loads(line) for line in response if line.strip()) if streamed else (json.load(response),)
    for item in items:
        if not isinstance(item, dict):
            raise ProviderError("Ollama returned an invalid chat response.")
        if item.get("error"):
            raise ProviderError("Ollama: " + redact(str(item["error"]))[:1200])
        message = item.get("message") or {}
        if not isinstance(message, dict):
            raise ProviderError("Ollama returned an invalid message.")
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ProviderError("Ollama returned invalid reply text.")
        if streamed and message.get("tool_calls"):
            raise ProviderError("Unexpected tool call in a conversational reply. Retry the saved message.")
        if content:
            parts.append(content)
            if streamed:
                publish(content)  # Never publish the separate private thinking field.
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list) or not all(isinstance(call, dict) for call in tool_calls):
            raise ProviderError("Ollama returned invalid tool calls. Your saved task is retained.")
        for call in tool_calls:
            if not isinstance(call.get("id"), str) or not call["id"]:
                call["id"] = "ollama-" + uuid4().hex
        calls.extend(tool_calls)
        if item.get("done") is True:
            final = item
            break
    if final is None:
        raise ProviderError("The Ollama reply stream was interrupted. Your message is saved; retry to resume.")
    if final.get("done_reason") in {"length", "max_tokens"}:
        raise ProviderError("Ollama reached the reply/thinking token limit before finishing. Your saved task is retained; no automatic retry was made.")
    if not parts and not calls:
        raise ProviderError("Ollama returned no final answer (its thinking may have used the reply budget). Your saved task is retained.")
    return {"id": final.get("created_at"), "choices": [{"message": {"role": "assistant", "content": "".join(parts),
        "tool_calls": calls}, "finish_reason": final.get("done_reason", "stop")}], "usage": {
            key: final.get(key) for key in ("prompt_eval_count", "eval_count", "eval_duration", "load_duration")}}


def chat(settings, payload, *, timeout):
    model = payload["model"]
    selected = profile(settings, model, metadata(settings, model), conversational=bool(payload.get("stream")))
    candidate = deepcopy(payload)
    candidate["max_tokens"] = selected["options"]["num_predict"]
    try:
        candidate = budget(candidate, selected["options"]["num_ctx"])
    except ProviderError:
        record(settings, "ollama", "error", "context_budget_rejected", model=model,
            context_tokens=selected["options"]["num_ctx"], estimated_input_byte_bound=estimate_input(candidate),
            message_sizes=[{"role": m.get("role"), "text_bytes": len(str(m.get("content", "")).encode("utf-8")),
                            "images": len(m.get("images", []))} for m in candidate.get("messages", [])],
            tools=len(candidate.get("tools", [])))
        raise
    selected["options"]["num_predict"] = candidate["max_tokens"]
    native = {"model": model, "messages": native_messages(candidate["messages"]),
              "stream": bool(candidate.get("stream")), "truncate": False, "shift": False, **selected}
    if candidate.get("tools"):
        native["tools"] = candidate["tools"]
    response_format = candidate.get("response_format", {})
    if not native.get("tools") and response_format.get("type") == "json_schema":
        native["format"] = response_format["json_schema"]["schema"]
    record(settings, "ollama", "info", "native_request_started", model=model,
        context_tokens=selected["options"]["num_ctx"], output_tokens=selected["options"]["num_predict"],
        estimated_input_byte_bound=estimate_input(candidate), thinking=selected.get("think"),
        messages=len(native["messages"]), tools=len(native.get("tools", [])))
    request = urllib.request.Request(settings.ollama_base_url + "/api/chat", data=json.dumps(native).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    try:
        with local_opener().open(request, timeout=timeout) as response:
            result = read_native(response, streamed=native["stream"])
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read(8192)).get("error", {})
            detail = error.get("message", "") if isinstance(error, dict) else str(error)
            detail = redact(detail)[:1200]
        except (OSError, ValueError, AttributeError):
            detail = "The local service did not provide an error description."
        record(settings, "ollama", "error", "native_request_failed", model=model, http_status=exc.code,
            context_tokens=selected["options"]["num_ctx"], detail=detail)
        hint = (" Reduce attached context or raise this model's OLLAMA_MODEL_CONTEXTS setting."
                if re.search(r"context|tokens|length", detail, re.I) else " Check the selected model and local Ollama service.")
        raise ProviderError(f"Ollama / {model} rejected the request (HTTP {exc.code}): {detail}.{hint} Your saved task is retained; no automatic retry was made.") from exc
    except (OSError, ValueError) as exc:
        record(settings, "ollama", "error", "native_request_failed", model=model, error_type=type(exc).__name__)
        raise ProviderError(f"Ollama / {model} request failed: {type(exc).__name__}. Your saved task is retained; check Console and retry.") from exc
    except ProviderError as exc:
        record(settings, "ollama", "error", "native_request_failed", model=model,
            context_tokens=selected["options"]["num_ctx"], detail=redact(str(exc))[:1200])
        raise
    usage = result["usage"]
    duration = usage.get("eval_duration") or 0
    record(settings, "ollama", "info", "native_request_complete", model=model,
        context_tokens=selected["options"]["num_ctx"], **usage,
        tokens_per_second=round((usage.get("eval_count") or 0) * 1e9 / duration, 2) if duration else None,
        elapsed_ms=round((time.monotonic() - started) * 1000))
    return result
