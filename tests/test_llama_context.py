from copy import deepcopy
import json

import pytest

from darius_api.llama_context import fit_payload
from darius_api.providers import LlamaCppPlannerProvider, OllamaPlannerProvider
from test_media_backend import settings_for
from test_opencode_provider import media_body, append_tool_result


@pytest.mark.parametrize("text", ["recreate the same image but Garvin is more mutated", "regenerate it", "rerender this"])
@pytest.mark.parametrize("provider_class", [LlamaCppPlannerProvider, OllamaPlannerProvider])
def test_recreate_uses_bounded_generation_and_saved_discovery(tmp_path, monkeypatch, text, provider_class):
    provider = provider_class(settings_for(tmp_path))
    monkeypatch.setattr(provider, "_visual_brief_response", lambda *a, **k: provider._local_message("", "Garvin in the vat with advanced mutation."))
    body = media_body(text)
    discovery = provider._responses(body)
    assert json.loads(discovery["output"][0]["arguments"])["operation"] == "discover_workflows"
    append_tool_result(body, discovery, {"workflows": [{"workflow_id": "qwen-template", "score": 100}]})
    inspect = provider._responses(body)
    assert json.loads(inspect["output"][0]["arguments"])["operation"] == "inspect_workflow"


def count(payload):
    return len(json.dumps(payload))


def test_catalog_compaction_preserves_ids_pairing_and_original():
    payload = {"max_tokens": 100, "messages": [
        {"role": "user", "content": "Garvin mutated"},
        {"role": "assistant", "tool_calls": [{"id": "one"}]},
        {"role": "tool", "tool_call_id": "one", "content": json.dumps({"workflows": [
            {"workflow_id": "chosen", "score": 100, "name": "Qwen", "slots": "x" * 10000}]})},
    ]}
    original = deepcopy(payload)
    result = fit_payload(payload, 1800, count)
    assert count(result) <= 1444
    assert result["messages"][1] == payload["messages"][1]
    assert result["messages"][2]["tool_call_id"] == "one"
    assert json.loads(result["messages"][2]["content"])["workflows"][0]["workflow_id"] == "chosen"
    assert payload == original


def test_registered_inspection_keeps_authoritative_fields_bounds_and_pairing_once():
    manifest = {"status": "ready", "source_digest": "source", "scene_slots": ["1.text"],
        "fields": [{"slot": "1.text", "value": "old subject" * 100, "role": "scene"},
                   {"slot": "2.text", "value": "Never change instructions", "role": "system"}],
        "block_party": {"parameters": [{"node_id": "1", "key": "text", "type": "string", "default": "old subject" * 100},
            {"node_id": "3", "key": "steps", "type": "integer", "min": 20, "max": 20, "step": 1, "default": 20}]}}
    evidence = {"workflow_id": "base", "graph": {"large": "x" * 10000},
        "slots": {"slots": [{"value": "x" * 10000}]}, "prompt_structure": {"positive": "x" * 10000},
        "recipe_manifest": manifest, "image_binding_slots": [], "readiness": {"ready": True}}
    payload = {"max_tokens": 2048, "messages": [
        {"role": "assistant", "tool_calls": [{"id": "inspect", "function": {"name": "comfyui", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "inspect", "content": json.dumps(evidence)}]}
    original = deepcopy(payload)
    result = fit_payload(payload, 8192, count)
    retained = json.loads(result["messages"][1]["content"])
    assert not ({"graph", "slots", "prompt_structure"} & retained.keys())
    assert retained["recipe_manifest"]["fields"] == manifest["fields"]
    assert retained["recipe_manifest"]["scene_slots"] == ["1.text"]
    assert "default" not in retained["recipe_manifest"]["block_party"]["parameters"][0]
    assert retained["recipe_manifest"]["block_party"]["parameters"][1] == manifest["block_party"]["parameters"][1]
    assert result["messages"][1]["tool_call_id"] == "inspect" and result["messages"][0] == payload["messages"][0]
    assert payload == original


def test_history_compaction_preserves_request_scene_focus_and_latest_messages():
    context = {"messages": [{"content": "old" * 500}] * 8 + [{"content": "Latest Garvin scene"}] * 4,
               "production_context": {"scene_id": "vat"}, "characters": [{"name": "Garvin"}]}
    payload = {"messages": [{"role": "user", "content": json.dumps({"request": "recreate it with mutation", "context": context})}]}
    result = fit_payload(payload, 2100, count)
    envelope = json.loads(result["messages"][0]["content"])
    assert envelope["request"] == "recreate it with mutation"
    assert envelope["context"]["production_context"] == {"scene_id": "vat"}
    assert envelope["context"]["characters"] == context["characters"]
    assert len(envelope["context"]["messages"]) == 4
    assert len(context["messages"]) == 12


def test_oversized_current_request_stops_without_truncation():
    payload = {"messages": [{"role": "user", "content": "current subject" * 1000}]}
    with pytest.raises(ValueError, match="still exceeds"):
        fit_payload(payload, 2000, count)


def test_local_budget_uses_server_template_tokenizer_and_limit(tmp_path, monkeypatch):
    provider = LlamaCppPlannerProvider(settings_for(tmp_path))
    calls = []
    def server(endpoint, payload=None):
        calls.append(endpoint)
        if endpoint == "/props":
            return {"default_generation_settings": {"n_ctx": 16384}}
        if endpoint == "/apply-template":
            return {"prompt": json.dumps(payload)}
        return {"tokens": list(range(len(payload["content"]) // 2))}
    monkeypatch.setattr(provider, "_context_server_json", server)
    payload = {"messages": [{"role": "tool", "content": json.dumps({"workflows": [{"workflow_id": "id", "slots": "x" * 40000}]})}]}
    result = provider._budget_chat_payload(payload)
    assert len(json.dumps(result)) < 1000
    assert calls == ["/props", "/apply-template", "/tokenize"]


def test_truncated_saved_tool_call_is_safe_history_not_executable_repair(tmp_path):
    provider = LlamaCppPlannerProvider(settings_for(tmp_path))
    raw = '{"operation":"prepare_workflow","arguments":{"prompt":"unfinished video'
    items = [{"type": "function_call", "call_id": "bad", "name": "comfyui", "arguments": raw},
             {"type": "function_call_output", "call_id": "bad", "output": '{"error":"Invalid JSON. No action executed."}'}]
    original = deepcopy(items)
    messages = provider._chat_messages(items)
    args = json.loads(messages[0]["tool_calls"][0]["function"]["arguments"])
    assert args["_invalid_json_arguments"] == raw
    assert "operation" not in args
    assert messages[1]["tool_call_id"] == "bad"
    assert "Invalid JSON" in messages[1]["content"]
    assert items == original
    assert provider._chat_max_tokens(True) == 2048
    assert OllamaPlannerProvider(settings_for(tmp_path))._chat_max_tokens(True) == 4096


def test_old_render_history_compacts_without_erasing_recent_evidence():
    history = [{"workflow_id": str(i), "prompt": "old scene" * 100} for i in range(8)]
    context = {"workflow_history": history, "messages": [{"content": "Garvin becoming a chrysalid"}] * 4}
    payload = {"messages": [{"role": "user", "content": json.dumps({"request": "next video", "context": context})}]}
    result = fit_payload(payload, 4000, count)
    compact = json.loads(result["messages"][0]["content"])["context"]
    assert compact["workflow_history"][-2:] == history[-2:]
    assert len(compact["workflow_history"]) < len(history)
    assert compact["messages"] == context["messages"]
    assert len(history) == 8


def test_context_timeout_retries_only_metadata_and_logs_endpoint(tmp_path, monkeypatch):
    import io
    from darius_api.diagnostics import tail
    provider = LlamaCppPlannerProvider(settings_for(tmp_path))
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, timeout))
            if len(calls) == 1:
                raise TimeoutError("slow model wake")
            return io.BytesIO(b'{"tokens": [1, 2]}')
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    assert provider._context_server_json("/tokenize", {"content": "test"}) == {"tokens": [1, 2]}
    assert len(calls) == 2 and all(url.endswith("/tokenize") for url, _ in calls)
    assert all(timeout == 30 for _, timeout in calls)
    log = tail(provider.settings.data_dir / "diagnostics" / "backend.jsonl")
    assert "context_check_failed" in log and "/tokenize" in log and '"token_count": 2' in log
