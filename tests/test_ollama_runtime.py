from copy import deepcopy
from dataclasses import replace
import io
import json
from types import SimpleNamespace
import urllib.error

import pytest

from darius_api import ollama_runtime as runtime
from darius_api.providers import OllamaPlannerProvider, LlamaCppPlannerProvider, OpenCodePlannerProvider, ProviderError
from darius_api.reply_stream import reply_stream
from test_media_backend import settings_for


def details(limit=262144, thinking=True):
    return {"model_info": {"qwen35.context_length": limit},
            "capabilities": ["completion", "tools", "vision"] + (["thinking"] if thinking else [])}


def test_ornith_profile_has_real_context_and_task_specific_sampling(tmp_path):
    settings = settings_for(tmp_path)
    precise = runtime.profile(settings, "ornith-1.5:9b", details())
    assert precise["options"] == {"num_ctx": 32768, "num_predict": 8192,
        "temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
        "presence_penalty": 0.0, "repeat_penalty": 1.0}
    assert precise["think"] is True
    conversational = runtime.profile(settings, "ornith-1.5:9b", details(), conversational=True)
    assert conversational["options"]["temperature"] == 1.0
    assert conversational["options"]["num_predict"] == 2048
    assert conversational["think"] is False


def test_per_model_context_override_is_capped_at_model_limit(tmp_path):
    settings = replace(settings_for(tmp_path), ollama_model_contexts='{"ornith-1.5:9b":65536}')
    assert runtime.profile(settings, "ornith-1.5:9b", details())["options"]["num_ctx"] == 65536
    assert runtime.profile(settings, "ornith-1.5:9b", details(8192))["options"]["num_ctx"] == 8192
    other = runtime.profile(settings, "some-other:9b", details(thinking=False))
    assert other["options"]["num_ctx"] == 16384
    assert "think" not in other and "temperature" not in other["options"]


@pytest.mark.parametrize("value", ['[]', '{"ornith-1.5:9b":true}', '{"ornith-1.5:9b":999999}', 'broken'])
def test_invalid_override_explains_configuration(tmp_path, value):
    settings = replace(settings_for(tmp_path), ollama_model_contexts=value)
    with pytest.raises(ProviderError, match="OLLAMA_MODEL_CONTEXTS"):
        runtime.profile(settings, "ornith-1.5:9b", details())


def test_budget_compacts_old_history_without_changing_subject_ids_or_tool_pairs():
    context = {"messages": [{"content": "old background " * 1000}] * 16,
        "production_context": {"shot_id": "shot-one"}, "attached_asset_ids": ["project-image"]}
    payload = {"max_tokens": 1024, "messages": [
        {"role": "user", "content": json.dumps({"request": "A red dragon on Mars", "context": context})},
        {"role": "assistant", "tool_calls": [{"id": "call", "function": {"name": "comfyui", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call", "content": '{"workflow_id":"trusted"}'},
    ]}
    original = deepcopy(payload)
    result = runtime.budget(payload, 65536)
    envelope = json.loads(result["messages"][0]["content"])
    assert envelope["request"] == "A red dragon on Mars"
    assert envelope["context"]["production_context"] == context["production_context"]
    assert envelope["context"]["attached_asset_ids"] == ["project-image"]
    assert result["messages"][1] == payload["messages"][1]
    assert result["messages"][2]["tool_call_id"] == "call"
    assert json.loads(result["messages"][2]["content"]) == json.loads(payload["messages"][2]["content"])
    assert len(envelope["context"]["messages"]) < 16
    assert payload == original
    assert runtime.estimate_input(result) <= 65536 - 1024 - 256


def test_oversized_explicit_subject_is_not_truncated_or_submitted():
    payload = {"max_tokens": 512, "messages": [{"role": "user", "content": "the actual subject" * 1000}]}
    with pytest.raises(ProviderError, match="context budget"):
        runtime.budget(payload, 4096)


def test_native_messages_preserve_object_arguments_and_tool_ids():
    messages = [{"role": "assistant", "tool_calls": [{"id": "one", "function": {"name": "comfyui", "arguments": '{"operation":"inspect_workflow","arguments":{"workflow_id":"trusted"}}'}}]},
                {"role": "tool", "tool_call_id": "one", "content": "evidence"}]
    converted = runtime.native_messages(messages)
    assert converted[0]["tool_calls"][0]["function"]["arguments"]["operation"] == "inspect_workflow"
    assert converted[1]["tool_call_id"] == "one"
    assert converted[1]["tool_name"] == "comfyui"
    assert isinstance(messages[0]["tool_calls"][0]["function"]["arguments"], str)


def test_native_stream_publishes_only_answer_and_requires_completion():
    packets = [{"message": {"thinking": "private deliberation", "content": ""}, "done": False},
               {"message": {"content": "Hello café."}, "done": False},
               {"message": {"content": ""}, "done": True, "done_reason": "stop"}]
    events = []
    stream = io.BytesIO("\n".join(json.dumps(p) for p in packets).encode())
    with reply_stream(events.append):
        result = runtime.read_native(stream, streamed=True)
    assert events == [{"type": "delta", "text": "Hello café."}]
    assert result["choices"][0]["message"]["content"] == "Hello café."
    with pytest.raises(ProviderError, match="interrupted"):
        runtime.read_native(io.BytesIO(json.dumps(packets[1]).encode()), streamed=True)


@pytest.mark.parametrize("packet", [
    {"done": True, "done_reason": "length", "message": {"content": "partial"}},
    {"done": True, "message": {"thinking": "thinking only"}},
    {"error": "backend error"},
])
def test_incomplete_native_replies_are_not_saved_as_success(packet):
    with pytest.raises(ProviderError):
        runtime.read_native(io.BytesIO(json.dumps(packet).encode()), streamed=False)


@pytest.fixture
def native(tmp_path, monkeypatch):
    settings = replace(settings_for(tmp_path), ollama_model="ornith-1.5:9b")
    requests = []
    result = {"done": True, "done_reason": "stop", "message": {"content": '{"reply":"Ready","generation_prompt":null,"workflow_id":null}'},
              "prompt_eval_count": 5123, "eval_count": 20, "eval_duration": 1_000_000_000}
    def open_request(request, timeout):
        requests.append((request.full_url, json.loads(request.data)))
        return io.BytesIO(json.dumps(result).encode())
    monkeypatch.setattr(runtime, "metadata", lambda *args: details())
    monkeypatch.setattr(runtime, "local_opener", lambda: SimpleNamespace(open=open_request))
    return SimpleNamespace(settings=settings, requests=requests, result=result)


def test_native_transport_sets_context_sampling_schema_and_no_cloud_fields(native):
    provider = OllamaPlannerProvider(native.settings)
    body = {"input": [{"role": "user", "content": "Explain dramatic irony"}],
            "text": {"format": {"type": "json_schema", "name": "reply", "schema": {"type": "object"}}}}
    response = provider._responses(body)
    assert json.loads(response["output"][0]["content"][0]["text"])["reply"] == "Ready"
    url, payload = native.requests[0]
    assert url.endswith("/api/chat") and payload["model"] == "ornith-1.5:9b"
    assert payload["options"]["num_ctx"] == 32768 and payload["options"]["num_predict"] == 8192
    assert payload["think"] is True and payload["format"] == {"type": "object"}
    assert payload["shift"] is False
    assert payload["truncate"] is False
    assert "response_format" not in payload and "max_tokens" not in payload
    assert len(native.requests) == 1


def test_native_tool_call_returns_responses_envelope_without_executing_anything(native):
    native.result["message"] = {"tool_calls": [{"function": {"name": "comfyui", "arguments": {"operation": "asset_details", "arguments": {"asset_id": "one"}}}}]}
    provider = OllamaPlannerProvider(native.settings)
    result = provider._responses({"input": [{"role": "user", "content": "Tell me about available assets"}],
        "tools": [{"type": "function", "name": "comfyui", "parameters": {"properties": {"operation": {"enum": ["asset_details"]}}}}]})
    assert result["output"][0]["type"] == "function_call"
    assert json.loads(result["output"][0]["arguments"])["operation"] == "asset_details"
    assert len(native.requests) == 1


def test_native_http_error_has_context_counts_and_does_not_retry(native, monkeypatch):
    calls = []
    def reject(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError(request.full_url, 400, "Bad request", {},
            io.BytesIO(b'{"error":"request (5123 tokens) exceeds the available context size (4096 tokens)"}'))
    monkeypatch.setattr(runtime, "local_opener", lambda: SimpleNamespace(open=reject))
    with pytest.raises(ProviderError, match=r"5123 tokens.*4096 tokens"):
        OllamaPlannerProvider(native.settings)._responses({"input": [{"role": "user", "content": "hello"}]})
    assert len(calls) == 1
    log = (native.settings.data_dir / "diagnostics/backend.jsonl").read_text()
    assert "native_request_failed" in log and '"context_tokens": 32768' in log


def test_ollama_vision_survives_native_transport_and_ignores_base64_size(native):
    provider = OllamaPlannerProvider(native.settings)
    messages = provider._chat_messages([{"role": "user", "content": [
        {"type": "input_text", "text": "Describe this"},
        {"type": "input_image", "image_url": "data:image/png;base64,aGVsbG8="}]}])
    assert messages[0]["images"] == ["aGVsbG8="]
    assert messages[0]["content"] == "Describe this"
    large = deepcopy(messages)
    large[0]["images"] = ["x" * 1000000]
    assert runtime.estimate_input({"messages": messages}) == runtime.estimate_input({"messages": large})


def test_native_final_prose_is_a_safe_reply_not_a_format_error(native):
    native.result["message"] = {"content": "The catalog contains a Moss image workflow."}
    result = OllamaPlannerProvider(native.settings)._responses({"input": [{"role": "user", "content": "Tell me about workflows"}],
        "tools": [{"type": "function", "name": "comfyui", "parameters": {}}],
        "text": {"format": {"type": "json_schema", "name": "darius_reply", "schema": {"type": "object"}}}})
    answer = json.loads(result["output"][0]["content"][0]["text"])
    assert answer["reply"] == "The catalog contains a Moss image workflow."
    assert answer["workflow_id"] is None and answer["generation_prompt"] is None
    assert len(native.requests) == 1


def test_no_tools_final_turn_really_omits_native_tools_and_enforces_schema(native):
    OllamaPlannerProvider(native.settings)._responses({"input": [{"role": "user", "content": "Tell me about workflows"}],
        "tools": [{"type": "function", "name": "comfyui", "parameters": {}}], "tool_choice": "none",
        "text": {"format": {"type": "json_schema", "name": "darius_reply", "schema": {"type": "object"}}}})
    assert "tools" not in native.requests[0][1]
    assert native.requests[0][1]["format"] == {"type": "object"}


def test_gpu_handoff_only_applies_to_ollama_and_preserves_other_transports(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("darius_api.gpu_handoff.unload_idle_comfy", lambda settings: calls.append(True))
    settings = settings_for(tmp_path)
    OllamaPlannerProvider(settings)._prepare_gpu()
    assert calls == [True]
    assert LlamaCppPlannerProvider(settings)._plain_chat_uses_responses() is False
    assert OpenCodePlannerProvider(settings)._plain_chat_uses_responses() is True
    assert OpenCodePlannerProvider(settings)._chat_max_tokens(True) == 256


def test_native_missing_call_ids_are_unique_across_turns():
    packet = {"done": True, "message": {"tool_calls": [{"function": {"name": "comfyui", "arguments": {}}}]}}
    ids = [runtime.read_native(io.BytesIO(json.dumps(packet).encode()), streamed=False)["choices"][0]["message"]["tool_calls"][0]["id"] for _ in range(2)]
    assert ids[0] != ids[1]


def test_rejected_context_logs_sizes_not_user_text_and_does_not_infer(native):
    from darius_api.diagnostics import tail
    payload = {"model": "ornith-1.5:9b", "messages": [
        {"role": "user", "content": "PRIVATE SUBJECT " * 5000}]}
    with pytest.raises(ProviderError, match="context budget"):
        runtime.chat(native.settings, payload, timeout=10)
    log = tail(native.settings.data_dir / "diagnostics" / "backend.jsonl")
    assert "context_budget_rejected" in log and "text_bytes" in log
    assert "PRIVATE SUBJECT" not in log and not native.requests


def test_metadata_is_bounded_cached_and_does_not_load_a_model(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    monkeypatch.setattr(runtime, "_metadata_cache", {})
    requests = []
    def open_request(request, timeout):
        requests.append(request)
        assert timeout == 5
        assert request.full_url.endswith("/api/show")
        return io.BytesIO(json.dumps(details()).encode())
    monkeypatch.setattr(runtime, "local_opener", lambda: SimpleNamespace(open=open_request))
    assert runtime.metadata(settings, "ornith")["capabilities"] == details()["capabilities"]
    assert runtime.metadata(settings, "ornith")["capabilities"] == details()["capabilities"]
    assert len(requests) == 1


@pytest.mark.parametrize("url", ["http://example.com:11434", "https://127.0.0.1:11434", "http://user:secret@localhost:11434"])
def test_runtime_metadata_never_follows_remote_or_credentialed_endpoints(tmp_path, url):
    settings = replace(settings_for(tmp_path), ollama_base_url=url)
    with pytest.raises(ProviderError, match="loopback"):
        runtime.metadata(settings, "ornith")


def test_config_reads_per_model_budget_and_independent_cache_switch(tmp_path, monkeypatch):
    from darius_api.config import Settings
    monkeypatch.setenv("OLLAMA_CONTEXT_TOKENS", "8192")
    monkeypatch.setenv("OLLAMA_MODEL_CONTEXTS", '{"ornith-1.5:9b":65536}')
    monkeypatch.setenv("OLLAMA_UNLOAD_IDLE_COMFY", "false")
    settings = Settings.from_env()
    assert settings.ollama_context_tokens == 8192
    assert settings.ollama_model_contexts == '{"ornith-1.5:9b":65536}'
    assert settings.ollama_unload_idle_comfy is False
