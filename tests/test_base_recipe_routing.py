import json
from types import SimpleNamespace

import pytest

from darius_api.base_recipes import recipes
from darius_api.media_intent import output_kind, requested_count, resolve_request
from darius_api.trusted_workflows import route_context, validate_preferences, WorkflowPreferences
from darius_api.workflow_catalog import discover_workflows, record_conversion, refresh_conversion_failures


@pytest.fixture
def folder_setup(tmp_path):
    defaults, custom, data = (tmp_path / name for name in ("defaults", "custom", "data"))
    for path in (defaults, custom, data):
        path.mkdir()
    graph = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "A sample subject"}},
             "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "sample"}}}
    (defaults / "qwen_t2i.json").write_text(json.dumps(graph))
    (custom / "assistant-old.json").write_text(json.dumps(graph))
    settings = SimpleNamespace(comfy_workflow_defaults_root=defaults, comfy_workflow_root=custom, data_dir=data)
    registry = SimpleNamespace(enabled=lambda: [], get=lambda _: (_ for _ in ()).throw(KeyError()))
    return settings, registry


def test_default_discovery_never_uses_generated_or_custom_graphs(folder_setup):
    settings, registry = folder_setup
    assert [w["workflow_id"] for w in discover_workflows(settings, output_kind="image")["workflows"]] == ["qwen_t2i.json"]
    assert list(recipes(settings, registry)) == ["qwen_t2i.json"]


def test_service_failure_expires_and_refresh_preserves_render_evidence(folder_setup, monkeypatch):
    settings, _ = folder_setup
    from darius_api import workflow_catalog as catalog
    record_conversion(settings, "qwen_t2i.json", False, error="connection refused")
    cache = catalog._conversion_cache(settings)
    value = cache["defaults/qwen_t2i.json"]
    value.update(last_conversion_at="2020-01-01T00:00:00+00:00", render_success_count=21)
    monkeypatch.setattr(catalog, "_conversion_cache", lambda _: cache)
    assert discover_workflows(settings, output_kind="image")["workflows"][0]["conversion_status"] == "retry available"
    refresh_conversion_failures(settings)
    assert cache["defaults/qwen_t2i.json"]["successful"] is None
    assert cache["defaults/qwen_t2i.json"]["render_success_count"] == 21


def test_auto_route_uses_folder_base_not_previous_generated_workflow(folder_setup):
    settings, registry = folder_setup
    context = {"messages": [{"role": "assistant", "workflow_id": "assistant-old", "content": "An old subject"}]}
    route_context(SimpleNamespace(get=lambda *_: None), "project", registry, context, "Generate an image of a blue truck using qwen", settings)
    assert context["preferred_workflow_id"] == "qwen_t2i.json"
    assert context["workflow_route"]["source"] == "defaults-folder"
    assert context["workflow_policy"]["allowed_ids"] == ["qwen_t2i.json"]


def test_requested_missing_family_does_not_switch_to_another_model(folder_setup):
    settings, registry = folder_setup
    from fastapi import HTTPException
    with pytest.raises(HTTPException, match="matching krea"):
        route_context(SimpleNamespace(get=lambda *_: None), "project", registry, {}, "Use krea2 to generate an image of a blue truck", settings)


def test_folder_recipe_can_be_associated_with_an_action(folder_setup):
    settings, registry = folder_setup
    preference = WorkflowPreferences(enabled=True, entries=[{"workflow_id": "qwen_t2i.json", "purpose": "character-sheet", "is_default": True}])
    assert "qwen_t2i.json" in validate_preferences(None, "project", registry, preference, settings)


def test_multimode_video_folder_actions_are_not_locked_to_inferred_mode(folder_setup):
    from darius_api.trusted_workflows import compatible
    settings, registry = folder_setup
    (settings.comfy_workflow_defaults_root / "minimax_camera.json").write_text(json.dumps({
        "1": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
        "2": {"class_type": "VHS_LoadVideo", "inputs": {"video": "example.mp4"}},
        "3": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "video"}},
    }))
    recipe = recipes(settings, registry)["minimax_camera.json"]
    assert recipe.capability == "image-to-video"
    assert recipe.input_hints == {"image": True, "video": True}
    for purpose in ("text-to-video", "image-to-video", "video-to-video"):
        assert compatible(recipe, purpose)
        preference = WorkflowPreferences(enabled=True, entries=[{"workflow_id": recipe.id, "purpose": purpose, "is_default": True}])
        validate_preferences(None, "project", registry, preference, settings)
    assert not compatible(recipe, "text-to-image")
    # Strict cloud operation capabilities are not widened by a local-folder override.
    cloud = SimpleNamespace(capability="image-to-video", output=SimpleNamespace(kind="video"), required_inputs=[])
    assert not compatible(cloud, "text-to-video")


@pytest.fixture
def video_routing(folder_setup):
    from darius_api.database import Asset, Job
    settings, registry = folder_setup
    for name in ("Darius_H3_Minimax_fl2va_workflow.json", "Darius_MiniMax_H3_Camera_Control .json"):
        (settings.comfy_workflow_defaults_root / name).write_text(json.dumps({
            "1": {"class_type": "LoadImage", "inputs": {"image": "unrelated-example.png"}},
            "2": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"prompt": "Old sample", "image": ["1", 0]}},
            "3": {"class_type": "SaveVideo", "inputs": {"video": ["2", 0], "filename_prefix": "video"}},
        }))
    records = {(Asset, "angel"): SimpleNamespace(id="angel", kind="image", project_id="project"),
               (Job, "render"): SimpleNamespace(project_id="project", output_asset_ids=["angel"])}
    session = SimpleNamespace(get=lambda model, key: records.get((model, key)))
    context = {"messages": [{"role": "assistant", "content": "Render queued.", "job_id": "render"},
                            *[{"role": "user", "content": "Thanks"} for _ in range(14)]]}
    return settings, registry, session, context, records


@pytest.mark.parametrize("request_text", ["Generate a video of this angel", "Animate her", "Animate it",
    "Make a clip from that character", "Generate a video from the last image"])
def test_spoken_video_subject_uses_only_current_conversation_image(video_routing, request_text):
    settings, registry, session, context, _ = video_routing
    route_context(session, "project", registry, context, request_text, settings)
    assert context["workflow_policy"]["purpose"] == "image-to-video"
    assert context["workflow_route"]["reference_asset_ids"] == ["angel"]
    assert context["attached_asset_ids"] == ["angel"]


def test_full_spoken_workflow_name_overrides_ranking(video_routing):
    settings, registry, session, context, _ = video_routing
    route_context(session, "project", registry, context,
        "Okay, you found some workflows. Please use the Darius Mini Max H3 camera control. To generate a video of this angel.", settings)
    assert context["preferred_workflow_id"] == "Darius_MiniMax_H3_Camera_Control .json"
    assert context["workflow_route"]["source"] == "explicit"
    assert context["workflow_route"]["reference_asset_ids"] == ["angel"]


def test_fresh_text_video_does_not_silently_reuse_previous_image(video_routing):
    from fastapi import HTTPException
    settings, registry, session, context, _ = video_routing
    with pytest.raises(HTTPException, match="need a source image"):
        route_context(session, "project", registry, context, "Generate a video of an angel", settings)
    assert not context.get("attached_asset_ids")


@pytest.mark.parametrize("problem", ["foreign-job", "foreign-asset", "missing-asset", "no-output", "multiple", "multiple-jobs", "video-output", "no-history"])
def test_ambiguous_or_unowned_video_references_block_before_planning(video_routing, problem):
    from darius_api.database import Asset, Job
    from fastapi import HTTPException
    settings, registry, session, context, records = video_routing
    if problem == "foreign-job":
        records[(Job, "render")].project_id = "other-project"
    elif problem == "foreign-asset":
        records[(Asset, "angel")].project_id = "other-project"
    elif problem == "missing-asset":
        del records[(Asset, "angel")]
    elif problem == "no-output":
        records[(Job, "render")].output_asset_ids = []
    elif problem == "multiple":
        records[(Job, "render")].output_asset_ids.append("second")
        records[(Asset, "second")] = SimpleNamespace(id="second", kind="image", project_id="project")
    elif problem == "multiple-jobs":
        context["messages"][0]["task"] = {"job_ids": ["render", "second-render"]}
    elif problem == "video-output":
        records[(Asset, "angel")].kind = "video"
    else:
        context["messages"] = []
        context["jobs"] = [{"id": "render", "output_asset_ids": ["angel"]}]
    with pytest.raises(HTTPException):
        route_context(session, "project", registry, context, "Generate a video of this angel", settings)
    assert "preferred_workflow_id" not in context


def test_attached_image_takes_precedence_over_conversation(video_routing):
    from darius_api.database import Asset
    settings, registry, session, context, records = video_routing
    records[(Asset, "attached")] = SimpleNamespace(id="attached", kind="image", project_id="project")
    context["attached_asset_ids"] = ["attached"]
    route_context(session, "project", registry, context, "Generate a video of this angel", settings)
    assert context["workflow_route"]["reference_asset_ids"] == ["attached"]


def test_explicit_attachment_is_not_merged_with_an_old_pinned_image(video_routing):
    from darius_api.database import Asset
    settings, registry, session, context, records = video_routing
    records[(Asset, "attached")] = SimpleNamespace(id="attached", kind="image", project_id="project")
    context.update(attached_asset_ids=["attached"], project_memory={"reference_asset_ids": ["angel"]})
    route_context(session, "project", registry, context, "Animate this image", settings)
    assert context["workflow_route"]["reference_asset_ids"] == ["attached"]


def test_explicit_image_recipe_cannot_be_used_for_video(folder_setup):
    from fastapi import HTTPException
    settings, registry = folder_setup
    with pytest.raises(HTTPException, match="does not support this action"):
        route_context(SimpleNamespace(get=lambda *_: None), "project", registry,
            {"preferred_workflow_id": "qwen_t2i.json"}, "Generate a video of a forest", settings)


def test_multiple_trusted_recipes_without_default_ask_instead_of_guessing(folder_setup):
    from fastapi import HTTPException
    from darius_api.database import AssistantMemory
    settings, registry = folder_setup
    (settings.comfy_workflow_defaults_root / "second_t2i.json").write_bytes((settings.comfy_workflow_defaults_root / "qwen_t2i.json").read_bytes())
    memory = SimpleNamespace(context_json={"workflow_preferences": {"enabled": True, "entries": [
        {"workflow_id": name, "purpose": "text-to-image"} for name in ("qwen_t2i.json", "second_t2i.json")]}})
    session = SimpleNamespace(get=lambda model, key: memory if model == AssistantMemory else None)
    with pytest.raises(HTTPException, match="Which workflow"):
        route_context(session, "project", registry, {}, "Generate an image of a forest", settings)


def test_spoken_workflow_question_is_not_a_generation_request():
    from darius_api.media_intent import is_media_request
    for question in ("Could you tell me which workflow can be used to generate videos?",
                     "Okay, would you please list the workflows to generate videos?"):
        assert not is_media_request(question)
    assert is_media_request("Could you please generate a video of this angel?")


def test_spoken_phase_and_followup_preserve_count_and_subject():
    original = "Okay, then let's create the first two scenes and then animate them with Quinn."
    assert requested_count(original) == 2
    assert output_kind(original) == "image"
    assert requested_count("Generate all three") == 3
    assert requested_count("Render both") == 2
    assert requested_count("Generate an image of all three characters together") == 1
    previous = "Use qwen to generate an image of a blue truck"
    for followup in ("ok, generate it", "yes render that", "please create them"):
        assert previous in resolve_request(followup, {"messages": [{"role": "user", "content": previous}]})
    assert resolve_request("generate it", {"messages": [{"role": "user", "content": previous}, {"role": "assistant", "job_id": "queued"}]}) == "generate it"
    assert resolve_request("generate it", {"messages": [{"role": "user", "content": previous, "task": {"state": "cancelled"}}]}) == "generate it"


@pytest.mark.parametrize("provider_class", ["OpenAIPlannerProvider", "DeepSeekPlannerProvider", "OllamaPlannerProvider", "LlamaCppPlannerProvider", "OpenCodePlannerProvider"])
def test_selected_recipe_executes_without_extra_model_tool_planning(tmp_path, monkeypatch, provider_class):
    from copy import deepcopy
    from darius_api import providers
    from darius_api.comfy_assistant import TOOL_DEFINITIONS
    from test_media_backend import settings_for
    from darius_api.agent_harness import parse_assistant_answer
    provider = getattr(providers, provider_class)(settings_for(tmp_path))
    monkeypatch.setattr(provider, "ready", lambda: True)
    for hook in ("_prepare_gpu", "_release_gpu"):
        if hasattr(provider, hook):
            monkeypatch.setattr(provider, hook, lambda: None)
    prompt = "A blue delivery truck parked beside a sunlit warehouse."
    brief = {"generation_prompt": prompt, "reply": "Ready.", "shots": [{"prompt": prompt, "subject_ids": [], "reference_asset_ids": []}]}
    monkeypatch.setattr(provider, "_visual_brief_response", lambda *a, **k: {"output": [{"content": [{"text": json.dumps(brief)}]}]})
    monkeypatch.setattr(provider, "_responses", lambda *a, **k: pytest.fail("The selected recipe must not require model-chosen tool calls"))
    graph = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "Old example"}},
             "2": {"class_type": "KSampler", "inputs": {"positive": ["1", 0]}},
             "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "test"}}}
    prepared = deepcopy(graph)
    calls = []
    def tool(envelope, timeout):
        operation, args = envelope["operation"], envelope["arguments"]
        calls.append(operation)
        if operation == "inspect_workflow":
            current = prepared if args["workflow_id"] == "assistant-current" else graph
            return {"workflow_id": args["workflow_id"], "graph": deepcopy(current),
                    "image_binding_slots": [], "slots": {"slots": [{"address": "1.text", "node_type": "CLIPTextEncode", "value": current["1"]["inputs"]["text"]}]}}
        if operation == "prepare_workflow":
            prepared["1"]["inputs"]["text"] = args["overrides"]["1.text"]
            return {"workflow_id": "assistant-current"}
        if operation == "queue_local_render":
            assert prepared["1"]["inputs"]["text"] == prompt
            return {"job_id": "confirmed-job"}
        pytest.fail(operation)
    context = {"assistant_conversation": True, "allow_local_rendering": True,
               "preferred_workflow_id": "qwen_t2i.json",
               "preferred_workflow": {"id": "qwen_t2i.json", "execution_provider": "local-comfyui"},
               "workflow_policy": {"enabled": True, "purpose": "text-to-image", "instruction": "Use the base recipe."}}
    result = provider.plan(context, "Generate an image of a blue truck", tool_runner=tool, tool_definitions=TOOL_DEFINITIONS)
    answer = parse_assistant_answer(result["output"])
    assert "confirmed-job" not in answer["reply"]
    assert answer["workflow_execution"]["job_ids"] == ["confirmed-job"]
    assert calls.count("prepare_workflow") == calls.count("queue_local_render") == 1
    assert "discover_workflows" not in calls


def test_wrong_model_shot_count_is_repaired_once(tmp_path, monkeypatch):
    from darius_api.providers import OpenAIPlannerProvider
    from test_media_backend import settings_for
    provider = OpenAIPlannerProvider(settings_for(tmp_path))
    prompt = "A blue delivery truck parked beside a sunlit warehouse."
    shot = {"prompt": prompt, "subject_ids": [], "reference_asset_ids": []}
    calls = []
    def brief(body, timeout):
        calls.append(body)
        answer = {"reply": "Ready.", "generation_prompt": prompt, "shots": [shot, shot] if len(calls) == 1 else [shot]}
        return {"output": [{"content": [{"text": json.dumps(answer)}]}]}
    monkeypatch.setattr(provider, "_visual_brief_response", brief)
    body = {"input": [{"role": "user", "content": json.dumps({"request": "Generate an image of a blue truck", "context": {}})}]}
    assert provider._resolve_visual_prompt(body, 20)[0] == prompt
    assert len(calls) == 2


def test_api_refresh_discovers_new_file_and_persists_action_mapping(tmp_path, folder_setup):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from darius_api.main import create_app
    from test_media_backend import settings_for, create_project
    folders, _ = folder_setup
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    settings = replace(settings_for(tmp_path), comfy_workflow_defaults_root=folders.comfy_workflow_defaults_root, workflow_definitions_dir=definitions)
    with TestClient(create_app(settings)) as client:
        project = create_project(client)
        first = client.get("/api/v1/workflow-recipes")
        assert first.status_code == 200
        assert [w["id"] for w in first.json()["workflows"]] == ["qwen_t2i.json"]
        new = folders.comfy_workflow_defaults_root / "video_t2v.json"
        new.write_text(json.dumps({"1": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "video"}}}))
        refreshed = client.post("/api/v1/workflow-recipes/refresh")
        assert refreshed.status_code == 200
        assert "video_t2v.json" in {w["id"] for w in refreshed.json()["workflows"]}
        preference = {"enabled": True, "entries": [{"workflow_id": "video_t2v.json", "purpose": "text-to-video", "is_default": True}]}
        saved = client.put(f"/api/v1/projects/{project}/trusted-workflows", json=preference)
        assert saved.status_code == 200, saved.text
        assert client.post("/api/v1/workflow-recipes/refresh").status_code == 200
        loaded = client.get(f"/api/v1/projects/{project}/trusted-workflows").json()
        assert loaded["entries"] == preference["entries"]
        assert loaded["unavailable_ids"] == []


def test_global_defaults_inherit_per_action_and_explicit_choice_wins(folder_setup):
    from darius_api.database import AssistantMemory, GlobalWorkflowPreference
    settings, registry = folder_setup
    image = json.loads((settings.comfy_workflow_defaults_root / "qwen_t2i.json").read_text())
    (settings.comfy_workflow_defaults_root / "project_image.json").write_text(json.dumps(image))
    (settings.comfy_workflow_defaults_root / "global_video.json").write_text(json.dumps({"1": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "video"}}}))
    global_value = {"enabled": True, "entries": [
        {"workflow_id": "qwen_t2i.json", "purpose": "text-to-image", "is_default": True},
        {"workflow_id": "global_video.json", "purpose": "text-to-video", "is_default": True}]}
    project_value = {"enabled": True, "entries": [{"workflow_id": "project_image.json", "purpose": "text-to-image", "is_default": True}]}
    def session_for(project=None):
        def get(model, key):
            if model is GlobalWorkflowPreference:
                return SimpleNamespace(preferences_json=global_value)
            if model is AssistantMemory and project:
                return SimpleNamespace(context_json={"workflow_preferences": project})
            return None
        return SimpleNamespace(get=get)
    context = {}
    route_context(session_for(), "new-project", registry, context, "Generate an image of a blue truck", settings)
    assert context["preferred_workflow_id"] == "qwen_t2i.json"
    assert context["workflow_route"]["source"] == "global-default"
    context = {}
    route_context(session_for(project_value), "project", registry, context, "Generate an image of a blue truck", settings)
    assert context["preferred_workflow_id"] == "project_image.json"
    assert context["workflow_route"]["source"] == "project-default"
    context = {}
    route_context(session_for(project_value), "project", registry, context, "Generate a video of a blue truck", settings)
    assert context["preferred_workflow_id"] == "global_video.json"
    assert context["workflow_route"]["source"] == "global-default"
    context = {"preferred_workflow_id": "qwen_t2i.json"}
    route_context(session_for(project_value), "project", registry, context, "Generate an image of a blue truck", settings)
    assert context["workflow_route"]["source"] == "explicit"
    assert context["preferred_workflow_id"] == "qwen_t2i.json"
    project_value["entries"][0]["workflow_id"] = "removed.json"
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        route_context(session_for(project_value), "project", registry, {}, "Generate an image of a blue truck", settings)
    project_value["enabled"] = False
    context = {}
    route_context(session_for(project_value), "project", registry, context, "Generate an image of a blue truck", settings)
    assert context["workflow_route"]["source"] == "global-default"


def test_global_defaults_api_persists_without_modifying_project_preferences(tmp_path, folder_setup):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from darius_api.main import create_app
    from test_media_backend import settings_for, create_project
    folders, _ = folder_setup
    definitions = tmp_path / "isolated-definitions"
    definitions.mkdir()
    settings = replace(settings_for(tmp_path), comfy_workflow_defaults_root=folders.comfy_workflow_defaults_root, workflow_definitions_dir=definitions)
    desired = {"enabled": True, "entries": [{"workflow_id": "qwen_t2i.json", "purpose": "text-to-image", "is_default": True}]}
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/settings/workflow-defaults").json()["enabled"] is False
        first, second = create_project(client, "First"), create_project(client, "Second")
        assert client.put("/api/v1/settings/workflow-defaults", json=desired).status_code == 200
        for project in (first, second):
            prefs = client.get(f"/api/v1/projects/{project}/trusted-workflows").json()
            assert prefs["entries"] == []
            assert prefs["global_defaults"] == desired
        rejected = client.put("/api/v1/settings/workflow-defaults", json={"enabled": True, "entries": [
            {"workflow_id": "assistant-generated-draft", "purpose": "text-to-image", "is_default": True}]})
        assert rejected.status_code == 422
    with TestClient(create_app(settings)) as restarted:
        saved = restarted.get("/api/v1/settings/workflow-defaults").json()
        assert saved["enabled"] is True
        assert saved["entries"] == desired["entries"]
