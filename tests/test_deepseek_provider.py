from __future__ import annotations

import io
import json
import urllib.error
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from darius_api.comfy_assistant import TOOL_DEFINITIONS
from darius_api.main import create_app
from darius_api.providers import (
    DeepSeekPlannerProvider,
    OpenAIPlannerProvider,
    ProviderError,
    build_planner_provider,
)
from test_media_backend import create_project, settings_for


def _response(output: list[dict], response_id: str = "response-1") -> io.BytesIO:
    return io.BytesIO(json.dumps({"id": response_id, "status": "completed", "output": output}).encode())


def _final_output(reply: str = "Ready to help.") -> list[dict]:
    return [{
        "type": "message",
        "role": "assistant",
        "content": [{
            "type": "output_text",
            "text": json.dumps({
                "reply": reply,
                "generation_prompt": None,
                "workflow_id": None,
            }),
        }],
    }]


def _deepseek_settings(tmp_path):
    return replace(
        settings_for(tmp_path),
        llm_provider="deepseek",
        deepseek_api_key="deepseek-test-key",
        deepseek_model="deepseek-flash",
    )


def test_deepseek_readiness_and_provider_factory(tmp_path):
    settings = settings_for(tmp_path)
    assert isinstance(build_planner_provider(settings), OpenAIPlannerProvider)
    assert DeepSeekPlannerProvider(settings).ready() is False
    assert DeepSeekPlannerProvider(replace(settings, deepseek_api_key="key")).ready() is False

    configured = _deepseek_settings(tmp_path)
    provider = build_planner_provider(configured)
    assert isinstance(provider, DeepSeekPlannerProvider)
    assert provider.ready() is True

    with pytest.raises(ProviderError, match="Unsupported DARIUS_LLM_PROVIDER"):
        build_planner_provider(replace(settings, llm_provider="typo"))


def test_saved_parallel_visual_tools_are_paired_before_image_messages(tmp_path):
    provider = DeepSeekPlannerProvider(_deepseek_settings(tmp_path))
    image = {"role": "user", "content": [{"type": "input_image", "image_url": "data:image/jpeg;base64,AA=="}]}
    body = {"model": "old-provider-model", "input": [
        {"type": "function_call", "call_id": "a"},
        {"type": "function_call", "call_id": "b"},
        {"type": "function_call_output", "call_id": "a", "output": "{}"},
        image,
        {"type": "function_call_output", "call_id": "b", "output": "{}"},
    ]}
    prepared = provider._transport_body(body)
    assert prepared["model"] == "deepseek-flash"
    assert [item.get("call_id") for item in prepared["input"]] == ["a", "b", "a", "b", None]
    assert prepared["input"][-1] == image
    assert body["input"][3] == image  # Preserve the durable checkpoint.


def test_deepseek_responses_round_trip_preserves_tools_and_images(tmp_path, monkeypatch):
    provider = DeepSeekPlannerProvider(_deepseek_settings(tmp_path))
    captured: list[tuple[str, str | None, dict]] = []
    replies = iter([
        _response([{
            "type": "function_call",
            "call_id": "call-view",
            "name": "comfyui",
            "arguments": json.dumps({"operation": "view_assets", "arguments_json": "{}"}),
        }], "response-tool"),
        _response(_final_output("I inspected the image."), "response-final"),
    ])

    def urlopen(request, timeout):
        captured.append((request.full_url, request.get_header("Authorization"), json.loads(request.data)))
        return next(replies)

    def tool_runner(arguments, timeout):
        assert arguments["operation"] == "view_assets"
        return {
            "assets": [{"id": "asset-1"}],
            "_image_content": [{
                "type": "input_image",
                "image_url": "data:image/jpeg;base64,AA==",
                "detail": "low",
            }],
        }

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = provider.plan(
        {"assistant_conversation": True},
        "Inspect this picture",
        tool_runner=tool_runner,
        tool_definitions=TOOL_DEFINITIONS,
    )

    assert result["provider"] == "deepseek"
    assert result["response_id"] == "response-final"
    assert len(captured) == 2
    first = captured[0]
    assert first[0] == "https://api.deepseek.com/responses"
    assert first[1] == "Bearer deepseek-test-key"
    assert first[2]["model"] == "deepseek-flash"
    assert first[2]["text"]["format"]["type"] == "json_schema"
    assert first[2]["text"]["format"]["schema"]["additionalProperties"] is False
    assert "strict" not in first[2]["text"]["format"]
    assert first[2]["tools"][0]["name"] == "comfyui"
    assert "strict" not in first[2]["tools"][0]
    assert not {"store", "include", "parallel_tool_calls"}.intersection(first[2])

    history = captured[1][2]["input"]
    assert any(item.get("type") == "function_call" and item.get("call_id") == "call-view" for item in history)
    assert any(item.get("type") == "function_call_output" and item.get("call_id") == "call-view" for item in history)
    image_message = next(item for item in history if item.get("role") == "user" and isinstance(item.get("content"), list))
    assert image_message["content"][0] == {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64,AA==",
        "detail": "low",
    }


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (400, {"error": {"code": "invalid_request_error"}}, "HTTP 400"),
        (401, {"error": {"code": "authentication_error"}}, "credentials"),
        (403, {"error": {"code": "permission_denied"}}, "credentials"),
        (402, {"error": {"code": "insufficient_balance"}}, "quota or balance"),
        (429, {"error": {"code": "rate_limit_exceeded"}}, "rate limited"),
        (500, {"error": {"code": "server_error"}}, "temporarily unavailable"),
    ],
)
def test_deepseek_http_errors_are_actionable(tmp_path, monkeypatch, status, body, message):
    def failed(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            status,
            "failed",
            {},
            io.BytesIO(json.dumps(body).encode()),
        )

    monkeypatch.setattr("urllib.request.urlopen", failed)
    with pytest.raises(ProviderError, match=message):
        DeepSeekPlannerProvider(_deepseek_settings(tmp_path)).plan({}, "Hello")


def test_deepseek_timeout_is_provider_specific(tmp_path, monkeypatch):
    def timed_out(request, timeout):
        raise TimeoutError("mock timeout")

    monkeypatch.setattr("urllib.request.urlopen", timed_out)
    with pytest.raises(ProviderError, match="DeepSeek planner request failed: TimeoutError"):
        DeepSeekPlannerProvider(_deepseek_settings(tmp_path)).plan({}, "Hello")


def test_selected_deepseek_provider_persists_assistant_reply(tmp_path, monkeypatch):
    captured = []

    def urlopen(request, timeout):
        captured.append((request.full_url, json.loads(request.data)))
        return _response(_final_output("DeepSeek reply persisted."))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    app = create_app(_deepseek_settings(tmp_path))
    with TestClient(app) as client:
        assert isinstance(app.state.planner_provider, DeepSeekPlannerProvider)
        project_id = create_project(client)
        conversation_id = client.post(
            f"/api/v1/projects/{project_id}/conversations", json={}
        ).json()["id"]
        user = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"role": "user", "content": "Hello"},
        ).json()
        reply = client.post(
            f"/api/v1/conversations/{conversation_id}/reply",
            json={"message_id": user["id"]},
        )
        assert reply.status_code == 200, reply.text
        assert reply.json()["content"] == "DeepSeek reply persisted."
        assert reply.json()["metadata"]["task"]["engine"] == "creative-helper"

    assert captured[0][0] == "https://api.deepseek.com/responses"
    assert captured[0][1]["model"] == "deepseek-flash"
    assert "include" not in captured[0][1]


def test_health_reports_selected_deepseek_without_secrets(tmp_path, monkeypatch):
    def unavailable(request, timeout):
        raise urllib.error.URLError("mock offline")

    settings = _deepseek_settings(tmp_path)
    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        payload = health.json()

    assert payload["components"]["openai"] == {
        "ready": False,
        "configured": False,
        "optional": True,
    }
    assert payload["components"]["deepseek"] == {
        "ready": True,
        "configured": True,
        "optional": True,
    }
    assert payload["components"]["llm"] == {
        "ready": True,
        "configured": True,
        "optional": True,
        "detail": "deepseek",
    }
    assert settings.deepseek_api_key not in json.dumps(payload)
