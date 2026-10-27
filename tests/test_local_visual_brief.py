import io
import json
from copy import deepcopy

import pytest

from darius_api.providers import LlamaCppPlannerProvider, OllamaPlannerProvider
from test_media_backend import settings_for
from test_opencode_provider import media_body, append_tool_result


@pytest.mark.parametrize("text", ["Generate three separate 10 second videos of Garvin", "Make three clips of Garvin"])
def test_plural_video_discovery_has_video_output(tmp_path, monkeypatch, text):
    provider = LlamaCppPlannerProvider(settings_for(tmp_path))
    monkeypatch.setattr(provider, "_resolve_visual_prompt", lambda *args: ("Garvin turns toward the camera in the vat bay.", ""))
    result = provider._responses(media_body(text))
    args = json.loads(result["output"][0]["arguments"])["arguments"]
    assert args["output_kind"] == "video"
    assert provider._needs_live_tools(text)


@pytest.mark.parametrize("provider_class", [LlamaCppPlannerProvider, OllamaPlannerProvider])
def test_local_subject_survives_discovery_inspection_preparation_retry(tmp_path, monkeypatch, provider_class):
    provider = provider_class(settings_for(tmp_path))
    visual = "Extreme close-up of Garvin's face and upper torso in the vat bay, chrysalis filaments spreading over his skin."
    captured = []
    def brief(body, timeout):
        captured.append(body)
        return {"output": [{"content": [{"text": json.dumps({"reply": "", "generation_prompt": visual, "workflow_id": None})}]}]}
    monkeypatch.setattr(provider, "_visual_brief_response", brief)
    request = "yes, please generate it using using qwen 2.1"
    body = media_body(request, {
        "messages": [{"role": "assistant", "content": "The next shot is a close-up of Garvin as chrysalis filaments spread."}],
        "scenes": [{"id": "vat", "description": "Garvin in the vat bay"}],
        "allow_local_rendering": True,
    })
    discovery = provider._responses(body)
    assert json.loads(discovery["output"][0]["arguments"])["arguments"]["query"] == request
    append_tool_result(body, discovery, {"workflows": [{"workflow_id": "qwen-template", "score": 1}]})
    body = deepcopy(body)
    inspect = provider._responses(body)
    append_tool_result(body, inspect, {"workflow_id": "qwen-template", "slots": {"slots": [
        {"address": "6.text", "node_type": "CLIPTextEncode", "value": "hedgehog example"}]}})
    prepare = provider._responses(body)
    assert json.loads(prepare["output"][0]["arguments"])["arguments"]["overrides"] == {"6.text": visual}
    append_tool_result(body, prepare, {"workflow_id": "correct-draft"})
    assert json.loads(provider._responses(body)["output"][0]["arguments"])["operation"] == "queue_local_render"
    assert len(captured) == 1
    supplied = json.loads(captured[0]["input"][1]["content"])
    assert supplied["context"]["scenes"][0]["id"] == "vat"


@pytest.mark.parametrize("prompt", [None, "yes, please generate it using qwen 2.1", "Could you generate this image please"])
def test_local_absent_or_command_echo_subject_never_prepares(tmp_path, monkeypatch, prompt):
    provider = LlamaCppPlannerProvider(settings_for(tmp_path))
    monkeypatch.setattr(provider, "_visual_brief_response", lambda *args, **kwargs: {
        "output": [{"content": [{"text": json.dumps({"reply": "Which shot?", "generation_prompt": prompt, "workflow_id": None})}]}]})
    response = provider._responses(media_body("yes, please generate it using qwen 2.1"))
    assert response["output"][0]["type"] == "message"
    assert json.loads(response["output"][0]["content"][0]["text"])["generation_prompt"] is None


@pytest.mark.parametrize("request_text", ["what does the last image you generated looks like", "why is the positive prompt not the subject of the scene and garvin?"])
def test_questions_do_not_enter_workflow_generation(tmp_path, monkeypatch, request_text):
    provider = LlamaCppPlannerProvider(settings_for(tmp_path))
    captured = []
    def respond(http_request, timeout):
        captured.append(json.loads(http_request.data))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": '{"reply":"Let us inspect its saved prompt.","generation_prompt":null,"workflow_id":null}'}}]}).encode())
    monkeypatch.setattr("urllib.request.urlopen", respond)
    response = provider._responses(media_body(request_text))
    assert response["output"][0]["type"] == "message"
    assert captured[0].get("tool_choice", "auto") == "auto"


def test_old_local_command_draft_cannot_queue_on_retry(tmp_path, monkeypatch):
    provider = LlamaCppPlannerProvider(settings_for(tmp_path))
    monkeypatch.setattr(provider, "_visual_brief_response", lambda *args, **kwargs: {
        "output": [{"content": [{"text": '{"reply":"","generation_prompt":"Garvin in the vat bay with alien filaments.","workflow_id":null}'}]}]})
    request = "yes, please generate it using qwen 2.1"
    body = media_body(request, {"allow_local_rendering": True})
    append_tool_result(body, provider._local_tool_call("prepare_workflow", {"overrides": {"6.text": request}}), {"workflow_id": "old-wrong-draft"})
    response = provider._responses(body)
    answer = json.loads(response["output"][0]["content"][0]["text"])
    assert "predates the prompt fix" in answer["reply"]
    assert answer["workflow_id"] is None


def test_subject_in_negative_only_graph_cannot_queue_on_retry(tmp_path, monkeypatch):
    provider = LlamaCppPlannerProvider(settings_for(tmp_path))
    prompt = "Garvin in the vat bay with alien filaments."
    monkeypatch.setattr(provider, "_visual_brief_response", lambda *args, **kwargs: {
        "output": [{"content": [{"text": json.dumps({"reply": "", "generation_prompt": prompt, "workflow_id": None})}]}]})
    body = media_body("generate an image of Garvin", {"allow_local_rendering": True})
    graph = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "An old hedgehog example"}},
             "7": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt}},
             "8": {"class_type": "KSampler", "inputs": {"positive": ["6", 0], "negative": ["7", 0]}}}
    append_tool_result(body, provider._local_tool_call("prepare_graph", {"graph": graph}), {"workflow_id": "wrong-negative-draft"})
    response = provider._responses(body)
    assert response["output"][0]["type"] == "message"
    assert "predates the prompt fix" in json.loads(response["output"][0]["content"][0]["text"])["reply"]
