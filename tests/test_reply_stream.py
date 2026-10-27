import io
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from darius_api.main import create_app
from darius_api.providers import OpenAIPlannerProvider, DeepSeekPlannerProvider, OllamaPlannerProvider, LlamaCppPlannerProvider, ProviderError
from darius_api.reply_stream import conversational, read_events, reply_stream
from test_media_backend import settings_for, create_project
from test_assistant import FakeAssistant


def sse(*events):
    return io.BytesIO("".join("data: " + (event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)) + "\n\n" for event in events).encode())


@pytest.mark.parametrize("text,expected", [
    ("Hello", True), ("Explain dramatic irony", True), ("Write a poem about rain", True),
    ("Hello, generate a film", False), ("Explain this", False),
    ("What is the job status?", False), ("Hey could you export a clip", False),
    ("What are good character names?", False), ("continue", False),
])
def test_conservative_routing(text, expected):
    assert conversational(text, {}, []) is expected
    assert not conversational(text, {"asset_ids": ["a"]}, [])
    assert not conversational(text, {"task": {"state": "interrupted"}}, [])


@pytest.mark.parametrize("provider_class,chat", [(OpenAIPlannerProvider, False), (DeepSeekPlannerProvider, False), (OllamaPlannerProvider, False), (LlamaCppPlannerProvider, True)])
def test_provider_streams_plain_chat_without_tools_or_schema(tmp_path, monkeypatch, provider_class, chat):
    settings = replace(settings_for(tmp_path), openai_api_key="test", deepseek_api_key="test", openai_planner_model="test", deepseek_model="test")
    events, requests = [], []
    def open_url(request, timeout):
        requests.append(json.loads(request.data))
        if provider_class is OllamaPlannerProvider:
            return io.BytesIO((json.dumps({"message": {"content": "Hello café."}, "done": False}) + "\n" + json.dumps({"done": True, "done_reason": "stop", "message": {"content": ""}}) + "\n").encode())
        if chat:
            return sse({"id": "r", "choices": [{"delta": {"content": "Hello café."}}]}, "[DONE]")
        return sse({"type": "response.output_text.delta", "delta": "Hello café."}, {"type": "response.completed", "response": {"id": "r"}})
    monkeypatch.setattr("urllib.request.urlopen", open_url)
    if provider_class is OllamaPlannerProvider:
        from types import SimpleNamespace
        monkeypatch.setattr("darius_api.ollama_runtime.metadata", lambda *args: {"model_info": {"test.context_length": 32768}, "capabilities": ["completion"]})
        monkeypatch.setattr("darius_api.ollama_runtime.local_opener", lambda: SimpleNamespace(open=open_url))
    provider = provider_class(settings)
    # Exercise the shared planner without local GPU discovery/release.
    monkeypatch.setattr(provider, "ready", lambda: True)
    with reply_stream(events.append):
        result = OpenAIPlannerProvider.plan(provider, {"assistant_mode": "conversation", "project": {"id": "p"}}, "Hello")
    assert events == [{"type": "delta", "text": "Hello café."}]
    assert json.loads(result["output"][0]["content"][0]["text"])["reply"] == "Hello café."
    assert requests[0]["stream"] is True
    assert "tools" not in requests[0] and "response_format" not in requests[0] and "text" not in requests[0]


def test_incomplete_and_failed_streams_are_not_success():
    with pytest.raises(ValueError, match="interrupted"):
        read_events(sse({"type": "response.output_text.delta", "delta": "Partial"}))
    with pytest.raises(ValueError, match="could not complete"):
        read_events(sse({"type": "response.failed"}))
    with pytest.raises(ValueError, match="incomplete"):
        read_events(sse({"choices": [{"delta": {"content": "Partial"}, "finish_reason": "length"}]}, "[DONE]"), chat=True)


def test_first_delta_is_published_before_provider_completion():
    events = []
    def lines():
        yield b'data: {"type":"response.output_text.delta","delta":"First sentence."}\n'
        yield b'\n'
        assert events == [{"type": "delta", "text": "First sentence."}]
        yield b'data: {"type":"response.completed","response":{"id":"r"}}\n'
        yield b'\n'
    with reply_stream(events.append):
        assert read_events(lines())["id"] == "r"


def test_stream_endpoint_persists_retries_and_preserves_tool_context(tmp_path):
    provider = FakeAssistant()
    defaults = tmp_path / "defaults"; defaults.mkdir()
    (defaults / "image.json").write_text(json.dumps({"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "Base scene"}}, "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "image"}}}))
    with TestClient(create_app(replace(settings_for(tmp_path), comfy_workflow_defaults_root=defaults), planner_provider=provider)) as client:
        project = create_project(client)
        cid = client.post(f"/api/v1/projects/{project}/conversations", json={}).json()["id"]
        base = f"/api/v1/conversations/{cid}"
        user = client.post(base + "/messages", json={"role": "user", "content": "Hello"}).json()
        events = [json.loads(line) for line in client.post(base + "/reply/stream", json={"message_id": user["id"]}).text.splitlines()]
        final = events[-1]["message"]
        assert final["content"] == provider.answer["reply"]
        assert provider.calls[0][0]["assistant_mode"] == "creative-helper"
        assert "workflows" not in provider.calls[0][0]
        retry = client.post(base + "/reply/stream", json={"message_id": user["id"]})
        assert json.loads(retry.text)["message"]["id"] == final["id"]
        assert len(provider.calls) == 1
        user = client.post(base + "/messages", json={"role": "user", "content": "Generate a forest image"}).json()
        client.post(base + "/reply/stream", json={"message_id": user["id"]})
        assert 'workflows' not in provider.calls[-1][0]
        assert provider.calls[-1][0]['assistant_mode'] == 'creative-helper'
        assert client.get(f'/api/v1/jobs?project_id={project}').json() == []
        assert 'workflows' not in provider.calls[-1][0]
        assert client.get(f"/api/v1/jobs?project_id={project}").json() == []


def test_stream_error_keeps_saved_message_retryable(tmp_path):
    provider = FakeAssistant()
    provider.available = False
    with TestClient(create_app(settings_for(tmp_path), planner_provider=provider)) as client:
        project = create_project(client)
        cid = client.post(f"/api/v1/projects/{project}/conversations", json={}).json()["id"]
        base = f"/api/v1/conversations/{cid}"
        user = client.post(base + "/messages", json={"role": "user", "content": "Hello"}).json()
        event = json.loads(client.post(base + "/reply/stream", json={"message_id": user["id"]}).text)
        assert event["type"] == "error" and event["status"] == 503
        assert len(client.get(base + "/messages").json()) == 1
        provider.available = True
        assert json.loads(client.post(base + "/reply/stream", json={"message_id": user["id"]}).text)["type"] == "done"
