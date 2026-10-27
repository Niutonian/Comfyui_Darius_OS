from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from dataclasses import replace

from darius_api.providers import (
    OPENCODE_FREE_MODELS,
    OpenCodePlannerProvider,
    build_planner_provider,
    discover_opencode_models,
)
from test_media_backend import settings_for


def opencode_settings(tmp_path):
    return replace(settings_for(tmp_path), llm_provider="opencode", opencode_command="opencode-test",
                   opencode_model="nemotron-3.5-lightning-free")


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def event(text):
    return json.dumps({"type": "text", "sessionID": "session-1", "part": {"text": text}}) + "\n"


def test_factory_builds_isolated_opencode_provider(tmp_path):
    provider = build_planner_provider(opencode_settings(tmp_path))
    assert isinstance(provider, OpenCodePlannerProvider)
    assert provider.model_name == "nemotron-3.5-lightning-free"


def test_model_discovery_uses_installed_cli_and_falls_back(tmp_path, monkeypatch):
    settings = opencode_settings(tmp_path)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: completed(
        "opencode/paid-model\nopencode/zeta-free\nopencode/alpha-free\n"
    ))
    assert discover_opencode_models(settings, refresh=True) == ("alpha-free", "zeta-free")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("missing")))
    assert discover_opencode_models(settings, refresh=True) == ("alpha-free", "zeta-free")
    monkeypatch.setattr("darius_api.providers._opencode_model_cache", ("", 0.0, ()))
    assert discover_opencode_models(settings, refresh=True) == OPENCODE_FREE_MODELS


def test_cli_transport_uses_stdin_sandbox_and_normalizes_tool_calls(tmp_path, monkeypatch):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    captured = {}

    def run(command, **kwargs):
        captured["command"] = command
        captured["prompt"] = json.loads(kwargs["input"])
        answer = {"tool_call": {"name": "comfyui", "arguments": {
            "operation": "discover_workflows", "arguments": {"output_kind": "image", "source_kind": "none"}
        }}}
        return completed(event(json.dumps(answer)))

    monkeypatch.setattr("subprocess.run", run)
    result = provider._responses({
        "input": [{"role": "system", "content": "Use tools"}, {"role": "user", "content": "make an image"}],
        "tools": [{"type": "function", "name": "comfyui", "description": "tools", "parameters": {"type": "object"}}],
    })
    assert captured["command"][:4] == ["opencode-test", "run", "--pure", "--format"]
    assert "--dir" in captured["command"]
    assert captured["prompt"]["available_tools"][0]["name"] == "comfyui"
    call = result["output"][0]
    assert call["type"] == "function_call"
    assert json.loads(call["arguments"])["operation"] == "discover_workflows"


def test_cli_transport_normalizes_final_reply_and_omits_image_bytes(tmp_path, monkeypatch):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    captured = {}

    def run(command, **kwargs):
        captured.update(json.loads(kwargs["input"]))
        return completed(event('{"reply":"hello","generation_prompt":null,"workflow_id":null}'))

    monkeypatch.setattr("subprocess.run", run)
    result = provider._responses({"input": [{"role": "user", "content": [
        {"type": "input_text", "text": "hello"},
        {"type": "input_image", "image_url": "data:image/png;base64,secret"},
    ]}]})
    text = result["output"][0]["content"][0]["text"]
    assert json.loads(text)["reply"] == "hello"
    assert "base64" not in json.dumps(captured)


def test_muse_receives_short_lived_image_file_attachment(tmp_path, monkeypatch):
    settings = replace(opencode_settings(tmp_path), opencode_model="muse-spark-1.3-contributor-free")
    provider = OpenCodePlannerProvider(settings)
    captured = {}

    def run(command, **kwargs):
        file_index = command.index("--file") + 1
        path = command[file_index]
        captured["path"] = path
        captured["bytes"] = open(path, "rb").read()
        captured["prompt"] = kwargs["input"]
        return completed(event('{"reply":"I see a test image.","generation_prompt":null,"workflow_id":null}'))

    monkeypatch.setattr("subprocess.run", run)
    encoded = "data:image/png;base64," + __import__("base64").b64encode(b"safe-image-bytes").decode()
    provider._responses({"input": [{"role": "user", "content": [
        {"type": "input_text", "text": "Describe this."},
        {"type": "input_image", "image_url": encoded},
    ]}]})

    assert captured["bytes"] == b"safe-image-bytes"
    assert "Image attached to OpenCode" in captured["prompt"]
    assert not __import__("pathlib").Path(captured["path"]).exists()


def test_cli_failure_is_actionable(tmp_path, monkeypatch):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: completed(returncode=1, stderr="free model unavailable"))
    try:
        provider._responses({"input": [{"role": "user", "content": "hello"}]})
    except Exception as exc:
        assert "free model unavailable" in str(exc)
    else:
        raise AssertionError("provider failure was not raised")


def media_body(request, context=None):
    return {"input": [{"role": "user", "content": json.dumps({"request": request, "context": context or {}})}],
            "tools": [{"type": "function", "name": "comfyui"}]}


def append_tool_result(body, response, result):
    call = response["output"][0]
    body["input"].extend([call, {"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(result)}])
    return json.loads(call["arguments"])


def test_generation_resolves_scene_once_and_keeps_workflow_request_separate(tmp_path, monkeypatch):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    request = "could you generate this image using qwen 2.1"
    visual = "Wide establishing shot of Garvin inside a gritty industrial spaceship vat bay, alien filaments forming a chrysalis."
    captured = []

    def run(command, **kwargs):
        captured.append(json.loads(kwargs["input"]))
        return completed(event(json.dumps({"reply": "", "generation_prompt": visual, "workflow_id": None})))

    monkeypatch.setattr("subprocess.run", run)
    body = media_body(request, {
        "messages": [{"role": "assistant", "content": "Scene 1: Vat Bay - Chrysalis Transformation"}],
        "scenes": [{"id": "scene-1", "description": "Gritty military spaceship vat bay"}],
        "characters": [{"name": "Garvin", "description": "Pale, lanky military male"}],
        "project_memory": {"active_scene_id": "scene-1"},
        "allow_local_rendering": True,
    })
    discovery = provider._responses(body)
    assert json.loads(discovery["output"][0]["arguments"])["arguments"]["query"] == request
    append_tool_result(body, discovery, {"workflows": [{"workflow_id": "qwen-2-1", "score": 10}]})
    # The harness deep-copies/checkpoints requests between model turns.
    body = deepcopy(body)
    inspect = provider._responses(body)
    append_tool_result(body, inspect, {"workflow_id": "qwen-2-1", "slots": {"slots": [
        {"address": "6.text", "node_type": "CLIPTextEncode", "value": "example"}]}})
    prepare = provider._responses(body)
    arguments = append_tool_result(body, prepare, {"workflow_id": "prepared-1"})
    assert arguments["arguments"]["overrides"] == {"6.text": visual}
    queue = provider._responses(body)
    assert json.loads(queue["output"][0]["arguments"])["operation"] == "queue_local_render"
    append_tool_result(body, queue, {"job_id": "job-1"})
    answer = json.loads(provider._responses(body)["output"][0]["content"][0]["text"])
    assert answer["generation_prompt"] == visual
    assert len(captured) == 1
    envelope = json.loads(captured[0]["conversation"][1]["content"])
    assert envelope["context"]["project_memory"]["active_scene_id"] == "scene-1"
    assert envelope["context"]["characters"][0]["name"] == "Garvin"


def test_ambiguous_or_command_echo_brief_never_calls_workflow_tools(tmp_path, monkeypatch):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    request = "could you generate this image using qwen 2.1"
    for prompt in (None, request, "Could you generate an image please", ""):
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: completed(event(json.dumps({
            "reply": "Which scene should I depict?", "generation_prompt": prompt, "workflow_id": None}))))
        result = provider._responses(media_body(request))
        assert result["output"][0]["type"] == "message"
        assert json.loads(result["output"][0]["content"][0]["text"])["generation_prompt"] is None


def test_old_prepared_command_draft_cannot_be_queued_on_retry(tmp_path, monkeypatch):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: completed(event(json.dumps({
        "reply": "", "generation_prompt": "Garvin in the spaceship vat bay, dramatic industrial lighting.", "workflow_id": None}))))
    request = "generate this image using qwen 2.1"
    body = media_body(request, {"allow_local_rendering": True})
    append_tool_result(body, provider._local_tool_call("prepare_workflow", {
        "workflow_id": "qwen", "overrides": {"6.text": request}}), {"workflow_id": "old-draft"})
    response = provider._responses(body)
    answer = json.loads(response["output"][0]["content"][0]["text"])
    assert "predates the prompt fix" in answer["reply"]
    assert answer["workflow_id"] is None


def test_video_brief_preserves_duration_and_reference_binding(tmp_path, monkeypatch):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    visual = "Garvin slowly dissolves into alien filaments; the camera gently pushes into the dim spaceship vat bay."
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: completed(event(json.dumps({
        "reply": "", "generation_prompt": visual, "workflow_id": None}))))
    body = media_body("generate a video from this image for 5 seconds", {
        "attached_asset_ids": ["own-image"], "assets": [{"id": "own-image", "kind": "image"}]})
    discovery = provider._responses(body)
    append_tool_result(body, discovery, {"workflows": [{"workflow_id": "video-ref", "accepts_images_hint": True}]})
    inspect = provider._responses(body)
    append_tool_result(body, inspect, {"workflow_id": "video-ref", "image_binding_slots": ["1.image"], "slots": {"slots": [
        {"address": "6.text", "node_type": "CLIPTextEncode"}, {"address": "2.value", "node_type": "PrimitiveFloat"}]}})
    args = json.loads(provider._responses(body)["output"][0]["arguments"])["arguments"]
    assert args["overrides"] == {"6.text": visual, "2.value": 5.0}
    assert args["asset_bindings"] == {"1.image": "own-image"}


def test_explicit_new_subject_is_sent_with_prior_context_for_resolution(tmp_path, monkeypatch):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    captured = []
    def run(command, **kwargs):
        captured.append(json.loads(kwargs["input"]))
        return completed(event('{"reply":"","generation_prompt":"A red fox curled asleep in fresh snow, soft winter light.","workflow_id":null}'))
    monkeypatch.setattr("subprocess.run", run)
    body = media_body("generate an image of a red fox asleep in snow instead", {
        "messages": [{"role": "user", "content": "Spaceship vat bay"}]})
    provider._responses(body)
    saved = provider._original_request(body)[1]["_opencode_visual_brief"]
    assert "red fox" in saved["prompt"]
    assert "new explicit subject overrides" in captured[0]["conversation"][0]["content"]


def test_multi_reference_graph_uses_resolved_prompt_not_command(tmp_path, monkeypatch):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    visual = "Garvin drifts slowly in a glowing alien vat as filaments form around him."
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: completed(event(json.dumps({
        "reply": "", "generation_prompt": visual, "workflow_id": None}))))
    body = media_body("generate a video from this image", {
        "attached_asset_ids": ["own-image"], "assets": [{"id": "own-image", "kind": "image"}]})
    append_tool_result(body, provider._local_tool_call("inspect_workflow", {"workflow_id": "video-ref"}), {
        "workflow_id": "video-ref", "image_binding_slots": ["1.image", "2.image"],
        "slots": {"slots": [{"address": "6.text", "node_type": "CLIPTextEncode"}]},
        "graph": {"1": {"class_type": "LoadImage", "inputs": {"image": "first-example.png"}},
                  "2": {"class_type": "LoadImage", "inputs": {"image": "second-example.png"}},
                  "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old example"}}},
    })
    prepare = provider._responses(body)
    args = append_tool_result(body, prepare, {"workflow_id": "new-video-draft"})["arguments"]
    assert args["graph"]["6"]["inputs"]["text"] == visual
    assert "2" not in args["graph"]
    answer = json.loads(provider._responses(body)["output"][0]["content"][0]["text"])
    assert answer["generation_prompt"] == visual


def test_invalid_brief_and_exhausted_budget_cannot_prepare_workflow(tmp_path, monkeypatch):
    import pytest
    from darius_api.providers import ProviderError
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: completed(event("not JSON")))
    with pytest.raises(ProviderError, match="valid visual brief"):
        provider._responses(media_body("generate this image"))
    body = media_body("generate this image")
    body["tool_choice"] = "none"
    response = provider._responses(body)
    assert response["output"][0]["type"] == "message"


def hedgehog_workflow():
    graph = {
        "76": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "A hedgehog wearing a tiny party hat"}, "_meta": {"title": "Prompt"}},
        "100": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}, "_meta": {"title": "CLIP Text Encode (Negative Prompt)"}},
        "107": {"class_type": "CLIPTextEncode", "inputs": {"text": ["76", 0]}, "_meta": {"title": "CLIP Text Encode (Positive Prompt)"}},
        "96": {"class_type": "CFGGuider", "inputs": {"positive": ["107", 0], "negative": ["100", 0]}},
    }
    return {"workflow_id": "flux-klein", "graph": graph, "slots": {"slots": [
        {"address": "76.value", "value": graph["76"]["inputs"]["value"], "node_type": "PrimitiveStringMultiline"},
        {"address": "100.text", "value": "", "node_type": "CLIPTextEncode"},
    ]}}


def test_hedgehog_template_replaces_connected_positive_and_preserves_negative(tmp_path, monkeypatch):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    visual = "Wide establishing shot of Garvin in an industrial spaceship vat bay."
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: completed(event(json.dumps({
        "reply": "", "generation_prompt": visual, "workflow_id": None}))))
    body = media_body("generate an image of the scene")
    inspected = hedgehog_workflow()
    append_tool_result(body, provider._local_tool_call("inspect_workflow", {"workflow_id": "flux-klein"}), inspected)
    prepare = provider._responses(body)
    overrides = json.loads(prepare["output"][0]["arguments"])["arguments"]["overrides"]
    assert overrides == {"76.value": visual}
    graph = deepcopy(inspected["graph"])
    for address, value in overrides.items():
        node, key = address.split(".")
        graph[node]["inputs"][key] = value
    positive_encoder = graph[graph["96"]["inputs"]["positive"][0]]
    assert graph[positive_encoder["inputs"]["text"][0]]["inputs"]["value"] == visual
    assert graph["100"]["inputs"]["text"] == ""


def test_slot_selection_uses_connections_even_without_titles():
    inspected = hedgehog_workflow()
    for node in inspected["graph"].values():
        node.pop("_meta", None)
    assert OpenCodePlannerProvider._prompt_slot(inspected) == "76.value"
    inspected["slots"]["slots"] = inspected["slots"]["slots"][1:]
    assert OpenCodePlannerProvider._prompt_slot(inspected) is None


def test_retry_with_correct_text_in_negative_slot_is_not_queued(tmp_path, monkeypatch):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    visual = "Wide establishing shot of Garvin in an industrial spaceship vat bay."
    request = "generate an image of the scene"
    body = media_body(request, {"allow_local_rendering": True, "_opencode_visual_brief": {"request": request, "prompt": visual}})
    append_tool_result(body, provider._local_tool_call("inspect_workflow", {"workflow_id": "flux-klein"}), hedgehog_workflow())
    append_tool_result(body, provider._local_tool_call("prepare_workflow", {
        "workflow_id": "flux-klein", "overrides": {"100.text": visual}}), {"workflow_id": "wrong-slot-draft"})
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No model call expected")))
    response = provider._responses(body)
    assert response["output"][0]["type"] == "message"
    assert json.loads(response["output"][0]["content"][0]["text"])["workflow_id"] is None


def test_combined_positive_negative_encoder_keeps_positive_field_selectable():
    result = {"graph": {
        "10": {"class_type": "TextEncodeQwenImage21", "inputs": {"prompt": "old", "negative_prompt": "blurry"}},
        "20": {"class_type": "KSampler", "inputs": {"positive": ["10", 0], "negative": ["10", 1]}},
    }, "slots": {"slots": [
        {"address": "10.negative_prompt", "node_type": "TextEncodeQwenImage21", "value": "blurry"},
        {"address": "10.prompt", "node_type": "TextEncodeQwenImage21", "value": "old"},
    ]}}
    assert OpenCodePlannerProvider._prompt_slot(result) == "10.prompt"


def test_selected_registered_workflow_is_inspected_before_ranked_default(tmp_path):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    context = {"preferred_workflow_id": "chosen-qwen", "workflows": [{
        "id": "chosen-qwen", "name": "Chosen Qwen", "execution_provider": "local-comfyui", "output": {"kind": "image"}}]}
    body = media_body("generate an image of a fox", context)
    append_tool_result(body, provider._local_tool_call("discover_workflows", {}), {
        "workflows": [{"workflow_id": "default-flux.json", "score": 1000}]})
    call = provider._continue_local_workflow(body)
    assert json.loads(call["output"][0]["arguments"])["arguments"]["workflow_id"] == "chosen-qwen"
    compact = provider._project_context_for_prompt(context)
    assert compact["workflows"] == context["workflows"]  # Lightweight identities remain selectable.
    assert compact["preferred_workflow"]["id"] == "chosen-qwen"


def test_selected_workflow_failure_or_wrong_output_never_silently_falls_back(tmp_path):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    body = media_body("generate an image of a fox", {"preferred_workflow_id": "chosen", "preferred_workflow": {
        "id": "chosen", "execution_provider": "local-comfyui", "output": {"kind": "video"}}})
    append_tool_result(body, provider._local_tool_call("discover_workflows", {}), {"workflows": [{"workflow_id": "fallback.json"}]})
    assert provider._continue_local_workflow(body)["output"][0]["type"] == "message"
    append_tool_result(body, provider._local_tool_call("inspect_workflow", {"workflow_id": "chosen"}), {"error": "missing model"})
    answer = json.loads(provider._continue_local_workflow(body)["output"][0]["content"][0]["text"])
    assert "missing model" in answer["reply"] and "not switched" in answer["reply"]


def test_automatic_ranking_excludes_generated_drafts_and_failed_conversions():
    result = {"workflows": [
        {"workflow_id": "assistant-old-draft", "score": 9000},
        {"workflow_id": "broken.json", "conversion_status": "conversion failed", "score": 1000},
        {"workflow_id": "original-qwen.json", "score": 20},
    ]}
    assert OpenCodePlannerProvider._select_discovered_workflow(result, "generate an image") == "original-qwen.json"


def test_selected_cloud_workflow_remains_available_for_explicit_review(tmp_path):
    provider = OpenCodePlannerProvider(opencode_settings(tmp_path))
    body = media_body("generate an image of the scene", {"preferred_workflow_id": "flux-cloud", "preferred_workflow": {
        "id": "flux-cloud", "execution_provider": "bfl", "output": {"kind": "image"}}})
    append_tool_result(body, provider._local_tool_call("discover_workflows", {}), {"workflows": []})
    response = provider._continue_local_workflow(body, visual_prompt="Garvin inside the spaceship vat bay.")
    answer = json.loads(response["output"][0]["content"][0]["text"])
    assert answer["workflow_id"] == "flux-cloud"
    assert answer["generation_prompt"] == "Garvin inside the spaceship vat bay."
    assert "no paid request" in answer["reply"]
