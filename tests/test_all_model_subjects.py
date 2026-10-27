import io
import json
from dataclasses import replace

import pytest

from darius_api.providers import (OpenAIPlannerProvider, DeepSeekPlannerProvider,
    OllamaPlannerProvider, LlamaCppPlannerProvider, OpenCodePlannerProvider)
from darius_api.visual_subject import SubjectToolGuard
from test_media_backend import settings_for

PROVIDERS = [OpenAIPlannerProvider, DeepSeekPlannerProvider, OllamaPlannerProvider,
             LlamaCppPlannerProvider, OpenCodePlannerProvider]
PROMPT = "Close-up of Garvin in the spaceship vat bay, chrysalis filaments spreading across his face."


def message(prompt=None, workflow=None):
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
        "reply": "Prepared for review.", "generation_prompt": prompt, "workflow_id": workflow,
    })}]}]}


def call(operation, arguments):
    return {"output": [{"type": "function_call", "name": "comfyui", "call_id": operation,
                        "arguments": json.dumps({"operation": operation, "arguments": arguments})}]}


@pytest.mark.parametrize("provider_class", PROVIDERS)
def test_all_providers_preserve_subject_tools_vision_and_other_inputs(tmp_path, monkeypatch, provider_class):
    provider = provider_class(settings_for(tmp_path))
    monkeypatch.setattr(provider, "ready", lambda: True)
    brief_calls, actions = [], []
    image = {"type": "input_image", "image_url": "data:image/png;base64,c3ludGhldGlj"}
    def brief(request, timeout):
        brief_calls.append(request)
        assert request["model"] == provider._model()
        assert any(image in item.get("content", []) for item in request["input"] if isinstance(item.get("content"), list))
        return message(PROMPT)
    monkeypatch.setattr(provider, "_visual_brief_response", brief)
    responses = iter([
        call("view_assets", {"asset_ids": ["own-image"]}),
        call("inspect_workflow", {"workflow_id": "chosen"}),
        call("prepare_workflow", {"workflow_id": "chosen", "overrides": {"6.text": "generate it using Qwen", "7.text": "blurry", "8.seed": 123}, "asset_bindings": {"9.image": "own-image"}}),
        call("queue_local_render", {"workflow_id": "prepared"}),
        message("An incorrect old hedgehog subject", "prepared"),
    ])
    monkeypatch.setattr(provider, "_responses", lambda request, timeout: next(responses))
    graph = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old hedgehog"}},
             "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry"}},
             "8": {"class_type": "KSampler", "inputs": {"positive": ["6", 0], "negative": ["7", 0], "seed": 123}}}
    def runner(envelope, timeout):
        actions.append(envelope)
        operation, args = envelope["operation"], envelope["arguments"]
        if operation == "view_assets":
            return {"_image_content": [image]}
        if operation == "inspect_workflow":
            if args["workflow_id"] == "prepared":
                return {"graph": {**graph, "6": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT}}}}
            return {"graph": graph}
        if operation == "prepare_workflow":
            assert args["overrides"] == {"6.text": PROMPT, "7.text": "blurry", "8.seed": 123}
            assert args["asset_bindings"] == {"9.image": "own-image"}
            return {"workflow_id": "prepared"}
        return {"job_id": "synthetic-job"}
    # Exercise the shared plan with mocked transports; no real model/tool calls.
    result = OpenAIPlannerProvider.plan(provider, {"assistant_conversation": True,
        "project": {"id": "own-project"}, "messages": [{"role": "assistant", "content": "Garvin's vat bay close-up"}]},
        "generate this image using Qwen", tool_runner=runner,
        tool_definitions=[{"type": "function", "name": "comfyui"}])
    assert len(brief_calls) == 1
    assert actions[0]["operation"] == "view_assets"
    assert json.loads(result["output"][0]["content"][0]["text"])["generation_prompt"] == PROMPT


@pytest.mark.parametrize("provider_class", [OpenAIPlannerProvider, DeepSeekPlannerProvider])
def test_cloud_resolver_keeps_configured_transport_and_model(tmp_path, monkeypatch, provider_class):
    provider = provider_class(replace(settings_for(tmp_path), openai_planner_model="configured-openai", deepseek_model="deepseek-flash"))
    captured = []
    def respond(request, timeout):
        captured.append(request)
        return io.BytesIO(json.dumps(message(PROMPT)).encode())
    monkeypatch.setattr("urllib.request.urlopen", respond)
    body = {"input": [{"role": "user", "content": json.dumps({"request": "generate this image", "context": {"project": {"id": "own"}, "characters": [{"name": "Garvin"}]}})}]}
    assert provider._resolve_visual_prompt(body, 30)[0] == PROMPT
    assert captured[0].full_url == provider.responses_url
    payload = json.loads(captured[0].data)
    assert payload["model"] == provider._model()
    assert not payload.get("tools")


def test_informational_guard_never_prepares_or_queues():
    writes = []
    guard = SubjectToolGuard(lambda *args: writes.append(args), lambda timeout: PROMPT,
                             OpenAIPlannerProvider._prompt_slot, read_only=True)
    for operation in ("prepare_workflow", "prepare_graph", "queue_local_render"):
        assert "error" in guard({"operation": operation, "arguments": {}}, 20)
    assert not writes


def test_wrong_subject_in_saved_positive_never_queues():
    calls = []
    def runner(envelope, timeout):
        calls.append(envelope["operation"])
        return {"graph": {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old hedgehog"}}}}
    guard = SubjectToolGuard(runner, lambda timeout: PROMPT, OpenAIPlannerProvider._prompt_slot)
    assert "error" in guard({"operation": "queue_local_render", "arguments": {"workflow_id": "old"}}, 20)
    assert calls == ["inspect_workflow"]


@pytest.mark.parametrize("provider_class", [OpenAIPlannerProvider, DeepSeekPlannerProvider])
def test_cloud_ambiguity_stops_before_any_workflow_side_effect(tmp_path, monkeypatch, provider_class):
    provider = provider_class(settings_for(tmp_path))
    monkeypatch.setattr(provider, "ready", lambda: True)
    monkeypatch.setattr(provider, "_responses", lambda request, timeout: call("prepare_workflow", {"workflow_id": "chosen"}))
    monkeypatch.setattr(provider, "_visual_brief_response", lambda request, timeout: message())
    actions = []
    result = provider.plan({"assistant_conversation": True, "project": {"id": "own"}},
        "generate this image", tool_runner=lambda *args: actions.append(args), tool_definitions=[])
    assert not actions
    assert json.loads(result["output"][0]["content"][0]["text"])["generation_prompt"] is None


def test_cloud_manual_draft_keeps_chosen_paid_workflow_without_executing(tmp_path, monkeypatch):
    provider = OpenAIPlannerProvider(settings_for(tmp_path))
    monkeypatch.setattr(provider, "ready", lambda: True)
    monkeypatch.setattr(provider, "_responses", lambda request, timeout: message("generate it using flux", "chosen-paid-workflow"))
    monkeypatch.setattr(provider, "_visual_brief_response", lambda request, timeout: message(PROMPT))
    result = provider.plan({"assistant_conversation": True, "project": {"id": "own"}}, "generate this image using flux")
    answer = json.loads(result["output"][0]["content"][0]["text"])
    assert answer["workflow_id"] == "chosen-paid-workflow"
    assert answer["generation_prompt"] == PROMPT


def test_guard_preserves_bridge_activity_and_cancellation_hooks():
    class Bridge:
        def run(self, arguments, timeout):
            return {}
    bridge = Bridge()
    guard = SubjectToolGuard(bridge.run, lambda timeout: PROMPT, OpenAIPlannerProvider._prompt_slot)
    assert guard.__self__ is bridge


@pytest.mark.parametrize("string_arguments", [False, True])
def test_novel_graph_positive_fixed_without_changing_negative_or_reference(string_arguments):
    captured = []
    graph = {"1": {"class_type": "CustomTextEncode", "inputs": {"text": "generate it"}},
             "2": {"class_type": "CustomTextEncode", "inputs": {"text": "blurry"}},
             "3": {"class_type": "CustomSampler", "inputs": {"positive": ["1", 0], "negative": ["2", 0]}},
             "4": {"class_type": "LoadImage", "inputs": {"image": "bound.png"}}}
    guard = SubjectToolGuard(lambda envelope, timeout: captured.append(envelope) or {},
        lambda timeout: PROMPT, OpenAIPlannerProvider._prompt_slot)
    arguments = {"graph": graph, "asset_bindings": {"4.image": "own"}}
    envelope = {"operation": "prepare_graph", **({"arguments_json": json.dumps(arguments)}
                if string_arguments else {"arguments": arguments})}
    guard(envelope, 20)
    assert captured[0]["arguments"]["graph"]["1"]["inputs"]["text"] == PROMPT
    assert captured[0]["arguments"]["graph"]["2"]["inputs"]["text"] == "blurry"
    assert captured[0]["arguments"]["asset_bindings"] == {"4.image": "own"}
    assert graph["1"]["inputs"]["text"] == "generate it"


@pytest.mark.parametrize("arguments", ["broken json", "[]"])
def test_invalid_json_arguments_do_not_execute(arguments):
    actions = []
    guard = SubjectToolGuard(lambda *args: actions.append(args), lambda timeout: PROMPT,
                             OpenAIPlannerProvider._prompt_slot)
    assert "error" in guard({"operation": "prepare_graph", "arguments_json": arguments}, 20)
    assert not actions
