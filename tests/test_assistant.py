import json
import io
import urllib.error
from dataclasses import replace

import pytest

from fastapi.testclient import TestClient

from darius_api.main import create_app
from darius_api.providers import LlamaCppPlannerProvider, OllamaPlannerProvider, OpenAIPlannerProvider, ProviderError
from test_media_backend import settings_for, create_project


@pytest.fixture(autouse=True)
def stub_local_visual_brief(monkeypatch):
    # Unit workflow-control tests never contact a real local model.
    def brief(provider, request, timeout):
        text, _ = provider._original_request(request)
        prompt = "A dog moving gently in cinematic daylight." if "dog" in text else "A blue bird in soft daylight."
        return {"output": [{"content": [{"text": json.dumps({
            "reply": "", "generation_prompt": prompt, "workflow_id": None,
        })}]}]}
    monkeypatch.setattr(OllamaPlannerProvider, "_visual_brief_response", brief)


class FakeAssistant:
    def __init__(self):
        self.calls = []
        self.available = True
        self.answer = {"reply": "What mood would you like?", "generation_prompt": None, "workflow_id": None}

    def ready(self):
        return self.available

    def plan(self, context, text):
        self.calls.append((context, text))
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(self.answer)}]}]}


def test_contextual_reply_retry_and_generation_never_execute(tmp_path):
    provider = FakeAssistant()
    with TestClient(create_app(settings_for(tmp_path), planner_provider=provider)) as client:
        project = create_project(client)
        cid = client.post(f"/api/v1/projects/{project}/conversations", json={"title": "Darius assistant"}).json()["id"]
        base = f"/api/v1/conversations/{cid}"
        user = client.post(base + "/messages", json={"role": "user", "content": "Help me develop a scene"}).json()
        reply = client.post(base + "/reply", json={"message_id": user["id"]})
        assert reply.status_code == 200, reply.text
        assert reply.json()["content"] == "What mood would you like?"
        assert provider.calls[0][0]["project"]["id"] == project
        assert 'workflow_history' not in provider.calls[0][0]
        assert provider.calls[0][0]['assistant_mode'] == 'creative-helper'
        assert provider.calls[0][0]["messages"][-1]["content"] == user["content"]
        assert client.post(base + "/reply", json={"message_id": user["id"]}).json()["id"] == reply.json()["id"]
        assert len(provider.calls) == 1
        assert 'workflows' not in provider.calls[0][0]
        workflow = 'invented-workflow'
        provider.answer = {"reply": "Here is a direction to review.", "generation_prompt": "A moonlit forest", "workflow_id": workflow}
        user2 = client.post(base + "/messages", json={"role": "user", "content": "Generate a moonlit forest"}).json()
        response = client.post(base + "/reply", json={"message_id": user2["id"]})
        assert response.status_code == 200, response.text
        assert not response.json()['metadata'].get('workflow_id')
        assert len(provider.calls[-1][0]["messages"]) == 3
        assert client.get(f"/api/v1/jobs?project_id={project}").json() == []


def test_reply_failure_is_retryable_and_project_scoped(tmp_path):
    provider = FakeAssistant()
    provider.available = False
    with TestClient(create_app(settings_for(tmp_path), planner_provider=provider)) as client:
        project = create_project(client)
        cid = client.post(f"/api/v1/projects/{project}/conversations", json={}).json()["id"]
        other = client.post(f"/api/v1/projects/{project}/conversations", json={}).json()["id"]
        base = f"/api/v1/conversations/{cid}"
        user = client.post(base + "/messages", json={"role": "user", "content": "Develop a detailed forest scene concept"}).json()
        assert client.post(f"/api/v1/conversations/{other}/reply", json={"message_id": user["id"]}).status_code == 404
        assert client.post(base + '/reply', json={'message_id': user['id']}).status_code == 503
        assert len(client.get(base + '/messages').json()) == 1
        provider.available = True
        provider.answer.update(generation_prompt='A forest', workflow_id='invented-workflow')
        response = client.post(base + '/reply', json={'message_id': user['id']})
        assert response.status_code == 200
        assert not response.json()['metadata'].get('workflow_id')
        assert client.get(f'/api/v1/jobs?project_id={project}').json() == []
        provider.answer.update(generation_prompt=None, workflow_id=None)
        assert client.post(base + "/reply", json={"message_id": user["id"]}).status_code == 200


def test_openai_reply_uses_structured_output_and_explains_rate_limits(tmp_path, monkeypatch):
    settings = replace(settings_for(tmp_path), openai_api_key="test-key", openai_planner_model="test-model")
    captured = []

    def limited(request, timeout):
        captured.append(json.loads(request.data))
        raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {}, io.BytesIO(b'{"error":{"code":"insufficient_quota"}}'))

    monkeypatch.setattr("urllib.request.urlopen", limited)
    with pytest.raises(ProviderError, match="no available API quota"):
        OpenAIPlannerProvider(settings).plan({"assistant_conversation": True}, "Hello")
    assert captured[0]["text"]["format"]["strict"] is True
    assert captured[0]["store"] is False


def test_ollama_uses_template_first_workflow_guidance_without_limiting_cloud_planners(tmp_path):
    settings = settings_for(tmp_path)
    cloud = OpenAIPlannerProvider(replace(settings, openai_api_key="test", openai_planner_model="test"))
    local = OllamaPlannerProvider(replace(settings, ollama_model="test"))

    assert cloud._workflow_authoring_guidance() == ""
    guidance = local._workflow_authoring_guidance()
    assert "first call discover_workflows" in guidance
    assert "Use prepare_graph only" in guidance
    assert "validate once more" in guidance


def test_ollama_omits_full_workflow_contracts_from_its_prompt_context(tmp_path):
    settings = settings_for(tmp_path)
    context = {
        "workflows": [{"id": "image", "contract": {"inputs": "x" * 100_000}}],
        "project": {"name": "Local test"},
    }
    cloud = OpenAIPlannerProvider(replace(settings, openai_api_key="test", openai_planner_model="test"))
    local = OllamaPlannerProvider(replace(settings, ollama_model="test"))

    assert cloud._project_context_for_prompt(context) is context
    compact = local._project_context_for_prompt(context)
    assert compact["workflows"] == [{"id": "image"}]
    assert compact["workflow_catalog_note"].startswith("1 workflows")
    assert context["workflows"][0]["contract"]["inputs"] == "x" * 100_000


def _ollama_tool_request(operation, arguments, result, *, allow_rendering=False, context=None,
                         request="create an image using qwen 2.1 of a blue bird"):
    call_id = f"call-{operation}"
    context = {"allow_local_rendering": allow_rendering, **(context or {})}
    return {
        "tools": [{"type": "function", "name": "comfyui", "parameters": {}}],
        "input": [
            {"role": "user", "content": json.dumps({
                "context": context,
                "request": request,
            })},
            {"type": "function_call", "call_id": call_id, "name": "comfyui",
             "arguments": json.dumps({"operation": operation, "arguments": arguments})},
            {"type": "function_call_output", "call_id": call_id, "output": json.dumps(result)},
        ],
    }


def test_ollama_continues_discovery_without_a_second_model_tool_call(tmp_path):
    provider = OllamaPlannerProvider(replace(settings_for(tmp_path), ollama_model="test"))
    request = _ollama_tool_request("discover_workflows", {}, {"workflows": [
        {"workflow_id": "darius_image_flux.json", "name": "Darius Image Flux", "score": 1008},
        {"workflow_id": "darius_image_qwen_image_2_1_t2i.json", "name": "Qwen Image 2 1", "score": 1005},
    ]})

    response = provider._responses(request)
    call = response["output"][0]
    assert call["type"] == "function_call"
    assert json.loads(call["arguments"]) == {
        "operation": "inspect_workflow",
        "arguments": {"workflow_id": "darius_image_qwen_image_2_1_t2i.json"},
    }

    assert provider._select_discovered_workflow({"workflows": [
        {"workflow_id": "image-edit.json", "score": 9999, "accepts_images_hint": True},
        {"workflow_id": "text-to-image.json", "score": 1, "accepts_images_hint": False},
    ]}, "create a green bird") == "text-to-image.json"


def test_ollama_starts_video_discovery_without_model_serialization(tmp_path):
    provider = OllamaPlannerProvider(replace(settings_for(tmp_path), ollama_model="test"))
    asset_id = "00000000-0000-4000-8000-000000000123"
    request = {
        "tools": [{"type": "function", "name": "comfyui", "parameters": {}}],
        "input": [{"role": "user", "content": json.dumps({
            "context": {"assets": [{"id": asset_id, "kind": "image"}], "messages": []},
            "request": "animate this dog as a five second video",
        })}],
    }

    call = provider._responses(request)["output"][0]
    assert json.loads(call["arguments"]) == {"operation": "discover_workflows", "arguments": {
        "query": "animate this dog as a five second video", "output_kind": "video",
        "source_kind": "image", "limit": 30,
    }}


def test_ollama_prepares_inspected_prompt_slot_and_returns_review_draft(tmp_path):
    provider = OllamaPlannerProvider(replace(settings_for(tmp_path), ollama_model="test"))
    inspected = _ollama_tool_request("inspect_workflow", {"workflow_id": "qwen.json"}, {
        "workflow_id": "qwen.json",
        "slots": {"slots": [
            {"address": "10.negative_prompt", "node_type": "TextEncodeQwenImage21", "value": "blurry"},
            {"address": "10.prompt", "node_type": "TextEncodeQwenImage21", "value": "old prompt"},
        ]},
    })
    prepared_call = provider._responses(inspected)["output"][0]
    prepared = json.loads(prepared_call["arguments"])
    assert prepared["operation"] == "prepare_workflow"
    assert prepared["arguments"]["overrides"] == {
        "10.prompt": "A blue bird in soft daylight."
    }

    finished = _ollama_tool_request("prepare_workflow", {"overrides": {"10.prompt": "A blue bird in soft daylight."}}, {
        "workflow_id": "assistant-ready", "state": "draft",
    })
    answer = json.loads(provider._responses(finished)["output"][0]["content"][0]["text"])
    assert answer["workflow_id"] == "assistant-ready"
    assert answer["generation_prompt"] == "A blue bird in soft daylight."
    assert "Nothing has been rendered" in answer["reply"]


def test_ollama_video_prefers_reference_workflow_and_binds_project_image(tmp_path):
    provider = OllamaPlannerProvider(replace(settings_for(tmp_path), ollama_model="test"))
    candidates = {"workflows": [
        {"workflow_id": "Darius_Minimax_H3_Keyframes.json", "name": "Minimax H3 Keyframes",
         "score": 1040, "accepts_images_hint": True},
        {"workflow_id": "mcp_ref_image to video_minimax_h3_r2v.json", "name": "H3 reference video",
         "score": 40, "accepts_images_hint": True},
    ]}
    assert provider._select_discovered_workflow(
        candidates, "use it for an h3 minimax video", needs_reference=True,
    ) == "mcp_ref_image to video_minimax_h3_r2v.json"

    asset_id = "00000000-0000-4000-8000-000000000123"
    context = {"assets": [{"id": asset_id, "kind": "image"}], "messages": []}
    inspected = _ollama_tool_request(
        "inspect_workflow", {"workflow_id": "h3-r2v.json"},
        {"workflow_id": "h3-r2v.json", "slots": {"slots": [
            {"address": "138.value", "node_type": "PrimitiveStringMultiline", "value": "old prompt"},
            {"address": "132.value", "node_type": "PrimitiveFloat", "value": 10},
        ]}, "image_binding_slots": ["137.image", "139.image"], "graph": {
            "132": {"class_type": "PrimitiveFloat", "inputs": {"value": 10},
                    "_meta": {"title": "Float (Duration)"}},
            "136": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
                "prompt": ["138", 0], "ref_images.ref_image_0": ["137", 0],
                "ref_images.ref_image_1": ["139", 0]}},
            "137": {"class_type": "LoadImage", "inputs": {"image": "first.png"}},
            "138": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "old prompt"}},
            "139": {"class_type": "LoadImage", "inputs": {"image": "second.png"}},
        }},
        context=context, request="animate this dog into a 5 sec video",
    )
    envelope = json.loads(provider._responses(inspected)["output"][0]["arguments"])
    assert envelope["operation"] == "prepare_graph"
    prepared = envelope["arguments"]
    assert prepared["capability"] == "image-to-video"
    assert prepared["asset_bindings"] == {"137.image": asset_id}
    assert prepared["graph"]["138"]["inputs"]["value"] == "A dog moving gently in cinematic daylight."
    assert prepared["graph"]["132"]["inputs"]["value"] == 5
    assert "139" not in prepared["graph"]
    assert "ref_images.ref_image_1" not in prepared["graph"]["136"]["inputs"]


def test_ollama_skips_misclassified_template_after_inspection(tmp_path):
    provider = OllamaPlannerProvider(replace(settings_for(tmp_path), ollama_model="test"))
    request = _ollama_tool_request(
        "inspect_workflow", {"workflow_id": "misclassified-edit.json"},
        {"workflow_id": "misclassified-edit.json", "slots": {"slots": [
            {"address": "1.prompt", "node_type": "TextEncode", "value": "old"},
        ]}, "image_binding_slots": ["2.image"]},
        request="create an image of a green bird with metal armor",
    )
    request["input"][1:1] = [
        {"type": "function_call", "call_id": "discover", "name": "comfyui",
         "arguments": json.dumps({"operation": "discover_workflows", "arguments": {}})},
        {"type": "function_call_output", "call_id": "discover", "output": json.dumps({"workflows": [
            {"workflow_id": "misclassified-edit.json", "score": 100, "accepts_images_hint": False},
            {"workflow_id": "safe-t2i.json", "score": 90, "accepts_images_hint": False},
        ]})},
    ]

    call = provider._responses(request)["output"][0]

    assert json.loads(call["arguments"]) == {
        "operation": "inspect_workflow", "arguments": {"workflow_id": "safe-t2i.json"},
    }


def test_local_planner_skips_workflow_that_fails_inspection(tmp_path):
    provider = OllamaPlannerProvider(replace(settings_for(tmp_path), ollama_model="test"))
    request = _ollama_tool_request(
        "inspect_workflow", {"workflow_id": "broken-krea.json"},
        {"error": "Comfy MCP returned no structured envelope"},
        request="create an image of a green monster using krea 2",
    )
    request["input"][1:1] = [
        {"type": "function_call", "call_id": "discover", "name": "comfyui",
         "arguments": json.dumps({"operation": "discover_workflows", "arguments": {}})},
        {"type": "function_call_output", "call_id": "discover", "output": json.dumps({"workflows": [
            {"workflow_id": "broken-krea.json", "score": 100, "accepts_images_hint": False},
            {"workflow_id": "working-krea.json", "score": 90, "accepts_images_hint": False},
        ]})},
    ]

    call = provider._responses(request)["output"][0]

    assert json.loads(call["arguments"]) == {
        "operation": "inspect_workflow", "arguments": {"workflow_id": "working-krea.json"},
    }


def test_llamacpp_uses_chat_completions_with_thinking_disabled(tmp_path, monkeypatch):
    provider = LlamaCppPlannerProvider(replace(
        settings_for(tmp_path), llamacpp_model="qwen-test", llamacpp_base_url="http://127.0.0.1:8080",
    ))
    captured = []

    class Response(io.BytesIO):
        status = 200

    def respond(request, timeout):
        captured.append(json.loads(request.data))
        return Response(json.dumps({"id": "local", "choices": [{"message": {
            "content": json.dumps({"reply": "hello", "generation_prompt": None, "workflow_id": None}),
        }}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", respond)
    result = provider._responses({"input": [{"role": "user", "content": "hello"}], "tools": []})

    assert json.loads(result["output"][0]["content"][0]["text"])["reply"] == "hello"
    assert captured[0]["model"] == "qwen-test"
    assert captured[0]["reasoning_effort"] == "none"
    assert captured[0]["reasoning_budget_tokens"] == 0
    assert captured[0]["max_tokens"] == 512


def test_llamacpp_bounds_tool_loop_and_omits_inspected_graph(tmp_path):
    provider = LlamaCppPlannerProvider(replace(settings_for(tmp_path), llamacpp_model="qwen-test"))
    initial = {
        "tools": [{"type": "function", "name": "comfyui", "parameters": {}}],
        "input": [{"role": "user", "content": json.dumps({
            "context": {}, "request": "create an image of a green bird",
        })}],
    }
    call = provider._responses(initial)["output"][0]
    assert json.loads(call["arguments"])["operation"] == "discover_workflows"
    assert provider._model_handles_tool_result("discover_workflows", {}) is False
    assert provider._model_handles_tool_result("inspect_workflow", {}) is False

    items = [
        {"type": "function_call", "call_id": "inspect", "name": "comfyui",
         "arguments": json.dumps({"operation": "inspect_workflow", "arguments": {"workflow_id": "krea"}})},
        {"type": "function_call_output", "call_id": "inspect", "output": json.dumps({
            "workflow_id": "krea", "slots": {"slots": []}, "graph": {"1": {"huge": "x" * 10000}},
        })},
    ]
    messages = provider._chat_messages(items)
    assert provider._tool_operation_count({"input": items}, "inspect_workflow") == 1
    focused = json.loads(messages[-1]["content"])
    assert focused["workflow_id"] == "krea"
    assert "graph" not in focused
