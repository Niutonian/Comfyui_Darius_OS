from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from darius_api.agent_harness import parse_assistant_answer, run_assistant_graph
from darius_api.ollama_runtime import budget, estimate_input, profile
from darius_api.providers import OllamaPlannerProvider, OpenAIPlannerProvider
from darius_api.trusted_workflows import _named_recipe, route_context
from darius_api.visual_plan import normalize_plan
from darius_api.visual_subject import SubjectToolGuard
from darius_api.workflow_answers import catalog_answer
from darius_api.workflow_executor import WorkflowExecutor
from darius_api.workflow_registration import manifest
from test_base_recipe_routing import folder_setup
from test_media_backend import settings_for
from test_workflow_executor import record, final


def recipe(key, name, kind="image"):
    return SimpleNamespace(id=key, name=name, output=SimpleNamespace(kind=kind))


@pytest.mark.parametrize("text", ["Generate an image of a red dragon, run it with Moss",
    "Generate an image of a red dragon using Moss", "Use the Moss workflow to generate an image"])
def test_unique_spoken_moss_alias_selects_renderer(text):
    available = {"moss": recipe("moss", "Darius Moss Image"), "qwen": recipe("qwen", "Darius Qwen Image")}
    assert _named_recipe(text, available) == "moss"


def test_short_alias_never_guesses_between_multiple_recipes():
    available = {"a": recipe("a", "Darius Moss Image Base"), "b": recipe("b", "Darius Moss Image Variant")}
    with pytest.raises(HTTPException, match="more than one"):
        _named_recipe("Generate an image using Moss", available)


def test_character_name_is_not_a_renderer_selector():
    available = {"moss": recipe("moss", "Moss"), "qwen": recipe("qwen", "Qwen")}
    assert _named_recipe("Generate an image of Moss by the river using Qwen", available) == "qwen"
    assert _named_recipe("Generate an image of Moss by the river", available) is None


def test_spoken_alias_routes_to_folder_base_before_any_model_call(folder_setup):
    settings, registry = folder_setup
    source = settings.comfy_workflow_defaults_root / "qwen_t2i.json"
    (source.parent / "Darius_Moss_Image.json").write_bytes(source.read_bytes())
    context = {}
    route_context(SimpleNamespace(get=lambda *args: None), "project", registry, context,
        "Generate an image of a red dragon, run it with Moss", settings)
    assert context["preferred_workflow_id"] == "Darius_Moss_Image.json"
    assert context["workflow_route"]["source"] == "explicit"


def test_workflow_question_sees_darius_base_catalog_without_authorizing_render(folder_setup):
    settings, registry = folder_setup
    context = {}
    route_context(SimpleNamespace(get=lambda *args: None), "project", registry, context,
                  "Which workflows are installed in Darius?", settings)
    assert [w["id"] for w in context["workflows"]] == ["qwen_t2i.json"]
    assert "workflow_route" not in context and "preferred_workflow_id" not in context


def test_unrestricted_read_only_catalog_can_see_cloud_without_making_it_an_auto_default(folder_setup):
    from darius_api.base_recipes import FolderRecipe
    from darius_api.workflows import WorkflowOutput
    settings, registry = folder_setup
    registry.enabled = lambda: [FolderRecipe("bfl-cloud", "Cloud image", "text-to-image",
        WorkflowOutput(kind="image"), execution_provider="bfl")]
    session = SimpleNamespace(get=lambda *args: None)
    catalog = {}
    route_context(session, "project", registry, catalog, "Which workflows are available?", settings)
    assert {w["id"] for w in catalog["workflows"]} == {"qwen_t2i.json", "bfl-cloud"}
    assert "workflow_route" not in catalog
    render = {}
    route_context(session, "project", registry, render, "Generate an image of a blue truck", settings)
    assert render["preferred_workflow_id"] == "qwen_t2i.json"


def test_local_workflow_identity_summary_is_bounded_and_keeps_selected_renderer(tmp_path):
    provider = OllamaPlannerProvider(settings_for(tmp_path))
    workflows = [{"id": f"base-{i}", "name": f"Recipe {i}", "contract": {"graph": "x" * 10000}} for i in range(100)]
    context = {"workflows": workflows, "preferred_workflow_id": "base-99"}
    original = deepcopy(context)
    compact = provider._project_context_for_prompt(context)
    assert len(compact["workflows"]) == 64
    assert compact["preferred_workflow"]["id"] == "base-99"
    assert all("contract" not in w for w in compact["workflows"])
    assert context == original


def brief_context():
    return {"assets": [{"id": "old-image"}], "attached_asset_ids": [],
        "workflow_route": {"workflow_id": "moss.json", "name": "Darius Moss Image",
                           "purpose": "text-to-image", "reference_asset_ids": []}}


def proposed_plan():
    return {"generation_prompt": "A silver dragon resting in a greenhouse.", "shots": [{
        "prompt": "A silver dragon resting in a greenhouse.", "subject_ids": [],
        "reference_asset_ids": ["old-image"]}]}


def test_incidental_context_image_is_not_a_physical_text_recipe_input():
    context = brief_context()
    result = normalize_plan(proposed_plan(), context, "Generate a dragon image")
    assert result["shots"][0]["reference_asset_ids"] == []
    assert result["shots"][0]["context_reference_asset_ids"] == ["old-image"]


def test_explicit_attachment_is_never_silently_dropped():
    context = brief_context()
    context["attached_asset_ids"] = ["old-image"]
    assert normalize_plan(proposed_plan(), context, "Generate a dragon image")["shots"][0]["reference_asset_ids"] == ["old-image"]


def test_foreign_reference_cannot_hide_behind_text_only_normalization():
    plan = proposed_plan()
    plan["shots"][0]["reference_asset_ids"] = ["foreign-image"]
    with pytest.raises(ValueError, match="active project"):
        normalize_plan(plan, brief_context(), "Generate a dragon image")


@pytest.mark.parametrize("provider_type", [OpenAIPlannerProvider, OllamaPlannerProvider])
def test_visual_brief_receives_renderer_identity_and_binding_policy(tmp_path, monkeypatch, provider_type):
    provider = provider_type(settings_for(tmp_path))
    captured = []
    def respond(body, timeout):
        captured.append(body)
        answer = {**proposed_plan(), "reply": "Ready", "workflow_id": None}
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}]}
    monkeypatch.setattr(provider, "_visual_brief_response", respond)
    body = {"input": [{"role": "user", "content": json.dumps({"request": "Generate a dragon image using Moss", "context": brief_context()})}]}
    prompt, question = provider._resolve_visual_prompt(body, 30)
    assert prompt == proposed_plan()["generation_prompt"] and not question
    context = json.loads(captured[0]["input"][1]["content"])["context"]
    assert context["render_workflow"]["name"] == "Darius Moss Image"
    assert context["workflow_route"]["reference_asset_ids"] == []


def tiny_graph():
    return {"prompt": {"class_type": "CLIPTextEncode", "inputs": {"text": "A sample image"}},
            "save": {"class_type": "SaveImage", "inputs": {"images": ["prompt", 0], "filename_prefix": "base"}}}


def test_cached_plan_cannot_add_incidental_inputs_to_text_recipe(tmp_path):
    executor = WorkflowExecutor(settings_for(tmp_path))
    context = {**brief_context(), "preferred_workflow_id": "moss.json", "allow_local_rendering": False}
    body = {"input": []}
    graph = tiny_graph()
    plan = {"shots": [{"id": "shot-1", **proposed_plan()["shots"][0]}]}
    record(body, executor.next(body, "Generate a dragon image", context, proposed_plan()["generation_prompt"], plan),
        {"graph": graph, "recipe_manifest": manifest(graph)})
    prepared = executor.next(body, "Generate a dragon image", context, proposed_plan()["generation_prompt"], plan)
    arguments = json.loads(prepared["output"][0]["arguments"])["arguments"]
    assert arguments["asset_bindings"] == {} and arguments["capability"] == "text-to-image"


def test_subject_guard_normalizes_cached_advisory_references_without_rewriting_original():
    graph, calls = tiny_graph(), []
    def runner(envelope, timeout):
        calls.append(envelope)
        return {"graph": graph, "recipe_manifest": manifest(graph)} if envelope["operation"] == "inspect_workflow" else {"workflow_id": "prepared"}
    plan = {"shots": [{"id": "shot-1", **proposed_plan()["shots"][0]}]}
    guard = SubjectToolGuard(runner, lambda timeout: "A silver dragon resting in a greenhouse.", lambda inspection: "prompt.text",
        plan=lambda: plan, reference_context=brief_context)
    result = guard({"operation": "prepare_workflow", "arguments": {"workflow_id": "moss.json", "asset_bindings": {}}}, 30)
    assert result == {"workflow_id": "prepared"}
    assert calls[-1]["arguments"]["overrides"]["prompt.text"] == proposed_plan()["generation_prompt"]
    assert plan["shots"][0]["reference_asset_ids"] == ["old-image"]


def catalog_body():
    return {"input": [{"type": "function_call", "name": "comfyui", "call_id": "catalog",
        "arguments": json.dumps({"operation": "list_workflows", "arguments": {}})},
        {"type": "function_call_output", "call_id": "catalog", "output": json.dumps({"workflows": [
            {"workflow_id": "moss.json", "name": "Darius Moss Image", "capability": "text-to-image"}], "count": 1})}]}


def test_catalog_receipt_is_valid_non_executable_reply():
    answer = parse_assistant_answer(catalog_answer(catalog_body(), "List the workflows available to generate images")["output"])
    assert "Darius Moss Image" in answer["reply"]
    assert answer["generation_prompt"] is None and answer["workflow_id"] is None
    assert catalog_answer(catalog_body(), "Generate an image using Moss") is None
    assert catalog_answer(catalog_body(), "Which workflow is best? Compare these") is None


def test_workflow_listing_needs_one_tool_call_and_no_final_model_round_trip(tmp_path, monkeypatch):
    provider = OllamaPlannerProvider(settings_for(tmp_path))
    responses, tools = [], []
    monkeypatch.setattr(provider, "ready", lambda: True)
    def respond(body, timeout):
        responses.append(body)
        assert len(responses) == 1, "A catalog receipt must not require another model call"
        return {"output": [catalog_body()["input"][0]]}
    def runner(envelope, timeout):
        tools.append(envelope)
        return json.loads(catalog_body()["input"][1]["output"])
    monkeypatch.setattr(provider, "_responses", respond)
    result = OpenAIPlannerProvider.plan(provider, {"project": {"id": "project"}, "assistant_conversation": True,
        "task_id": "list-task", "workflows": []}, "List the workflows available to generate images",
        tool_runner=runner, tool_definitions=[{"type": "function", "name": "comfyui", "parameters": {}}])
    assert result["task"]["state"] == "replied"
    assert len(responses) == len(tools) == 1
    assert "Darius Moss Image" in parse_assistant_answer(result["output"])["reply"]


def test_ollama_format_repair_cannot_replay_tools(tmp_path):
    responses, tools = [], []
    base = {"model": "ornith", "tools": [{"type": "function", "name": "comfyui"}], "input": [
        {"role": "user", "content": json.dumps({"request": "Tell me about available assets", "context": {}})}]}
    def model(body, timeout):
        responses.append(body)
        if len(responses) == 1:
            return {"output": [catalog_body()["input"][0]]}
        if len(responses) == 2:
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"reply":"unfinished'}]}]}
        assert "tools" not in body and body["tool_choice"] == "none"
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"reply": "The assets were listed.", "generation_prompt": None, "workflow_id": None})}]}]}
    def runner(envelope, timeout):
        tools.append(envelope)
        return {"assets": []}
    result = run_assistant_graph(settings_for(tmp_path), base, "format-task", "project", model, runner, provider_name="ollama")
    assert len(tools) == 1 and len(responses) == 3
    assert result["task"]["state"] == "replied"


def test_information_answer_cannot_become_a_render_proposal(tmp_path):
    answer = {"reply": "Here are your workflows", "generation_prompt": "An invented sample", "workflow_id": "not-a-real-workflow"}
    body = {"input": [{"role": "user", "content": json.dumps({"request": "List available workflows", "context": {}})}]}
    result = run_assistant_graph(settings_for(tmp_path), body, "info", "project", lambda *args, **kwargs: {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}]}, None)
    parsed = parse_assistant_answer(result["output"])
    assert parsed["generation_prompt"] is None and parsed["workflow_id"] is None
    assert result["task"]["state"] == "replied"


def test_32k_budget_keeps_current_input_by_reducing_optional_reply_reservation():
    payload = {"max_tokens": 8192, "messages": [{"role": "user", "content": "x" * 25000}]}
    original = deepcopy(payload)
    bounded = budget(payload, 32768)
    assert bounded["max_tokens"] == 4096
    assert bounded["messages"] == payload["messages"] and payload == original
    assert estimate_input(bounded) <= 32768 - bounded["max_tokens"] - 256


def test_input_estimate_does_not_double_escape_json_context():
    content = json.dumps({"request": 'A "silver dragon"', "context": {"note": "\\\\" * 1000}})
    payload = {"messages": [{"role": "user", "content": content}]}
    assert estimate_input(payload) == 512 + 64 + len(content.encode())


def test_larger_model_does_not_inherit_the_small_models_context_override(tmp_path):
    settings = replace(settings_for(tmp_path), ollama_model_contexts='{"ornith-1.5:9b":131072,"ornith-1.5:35b":32768}')
    details = {"model_info": {"qwen35moe.context_length": 262144}, "capabilities": ["thinking"]}
    assert profile(settings, "ornith-1.5:35b", details)["options"]["num_ctx"] == 32768
    assert profile(settings, "ornith-1.5:9b", details)["options"]["num_ctx"] == 131072
