import json
from copy import deepcopy
from dataclasses import replace

import pytest

from darius_api.workflow_executor import WorkflowExecutor
from darius_api.workflow_registration import manifest, register, registered, compiled
from test_media_backend import settings_for


@pytest.fixture
def flux_graph():
    return {
        "18:17": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": ""}},
        "18:14": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "Expand the user's visual request. Output only the caption."}},
        "18:11": {"class_type": "TextGenerate", "inputs": {"prompt": ["18:17", 0], "system_prompt": ["18:14", 0]}},
        "18:4": {"class_type": "CLIPTextEncode", "inputs": {"text": ["18:11", 0]}},
        "18:5": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality"}},
        "18:7": {"class_type": "KSampler", "inputs": {"positive": ["18:4", 0], "negative": ["18:5", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["18:7", 0], "filename_prefix": "base"}},
    }


def record(body, response, result):
    call = response["output"][0]
    body["input"].append(call)
    body["input"].append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(result)})
    return json.loads(call["arguments"])


def final(response):
    return json.loads(response["output"][0]["content"][0]["text"])


def context():
    return {"preferred_workflow_id": "flux.json", "allow_local_rendering": True, "workflow_route": {"reference_asset_ids": []}}


def test_flux_system_instructions_are_not_a_second_scene(flux_graph):
    result = manifest(flux_graph)
    assert result["status"] == "ready"
    assert result["scene_slots"] == ["18:17.value"]
    assert set(result["protected_slots"]) == {"18:14.value", "18:5.text"}
    with pytest.raises(ValueError, match="protected"):
        manifest(flux_graph, {"18:14.value": "scene"})


def test_registration_is_source_bound_and_cache_never_contains_a_generated_prompt(tmp_path, flux_graph):
    defaults = tmp_path / "defaults"; defaults.mkdir()
    path = defaults / "flux.json"
    path.write_text(json.dumps(flux_graph))
    settings = replace(settings_for(tmp_path), comfy_workflow_defaults_root=defaults)
    saved = register(settings, "flux.json", flux_graph)
    assert saved["status"] == "ready"
    assert compiled(settings, "flux.json") == flux_graph
    path.write_text(json.dumps({**flux_graph, "new": {"class_type": "PreviewAny", "inputs": {}}}))
    assert registered(settings, "flux.json") is None
    assert compiled(settings, "flux.json") is None
    with pytest.raises(ValueError, match="changed"):
        register(settings, "flux.json", flux_graph, expected_source=saved["source_digest"])


def test_distinct_encoder_fields_need_one_time_explicit_mapping(flux_graph):
    graph = deepcopy(flux_graph)
    graph["18:4"]["inputs"]["text"] = "A standing woman"
    graph["other"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "Red costume detail"}}
    graph["18:7"]["inputs"]["positive_detail"] = ["other", 0]
    ambiguous = manifest(graph)
    assert ambiguous["status"] == "needs_mapping"
    resolved = manifest(graph, {"18:4.text": "scene", "other.text": "preserve"})
    assert resolved["status"] == "ready"
    assert resolved["scene_slots"] == ["18:4.text"]
    assert "other.text" in resolved["protected_slots"]


def test_executor_compiles_only_scene_then_confirms_actual_job(tmp_path, flux_graph):
    executor = WorkflowExecutor(settings_for(tmp_path))
    body, ctx, prompt = {"input": []}, context(), "A young angel with black hair and a white gown."
    inspect = executor.next(body, "Generate one image", ctx, prompt)
    record(body, inspect, {"graph": flux_graph, "recipe_manifest": manifest(flux_graph)})
    prepare = executor.next(body, "Generate one image", ctx, prompt)
    args = json.loads(prepare["output"][0]["arguments"])["arguments"]
    assert args["overrides"] == {"18:17.value": prompt}
    assert args["prompt_bindings"] == {"18:17.value": "shot"}
    assert args["expected_recipe_digest"] == manifest(flux_graph)["contract_digest"]
    record(body, prepare, {"workflow_id": "assistant-current"})
    queue = executor.next(body, "Generate one image", ctx, prompt)
    assert json.loads(queue["output"][0]["arguments"])["operation"] == "queue_local_render"
    record(body, queue, {"job_id": "confirmed-job"})
    answer = final(executor.next(body, "Generate one image", ctx, prompt))
    assert answer["workflow_execution"]["state"] == "queued"
    assert "confirmed-job" not in answer["reply"]
    assert answer["workflow_execution"]["job_ids"] == ["confirmed-job"]
    assert flux_graph["18:17"]["inputs"]["value"] == ""


@pytest.mark.parametrize("helper", [None, "MiniMaxH3SigmaShift", "ModelAttentionBackend", "ImageScaleToTotalPixels",
    "H3LocalCameraEditor", "ShowText|pysssss", "ModelPreviewOverrideKJ"])
def test_video_executor_binds_recovered_image_and_preserves_base(tmp_path, helper):
    graph = {"reference": {"class_type": "LoadImage", "inputs": {"image": "sample.png"}},
             "video": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"image": ["reference", 0], "prompt": "Sample scene"}},
             "save": {"class_type": "SaveVideo", "inputs": {"video": ["video", 0], "filename_prefix": "video"}}}
    if helper:
        graph["helper"] = {"class_type": helper, "inputs": {}}
    executor = WorkflowExecutor(settings_for(tmp_path))
    ctx = {**context(), "workflow_route": {"reference_asset_ids": ["angel"]}}
    body, request, prompt = {"input": []}, "Generate a video of this angel", "The angel slowly unfurls her wings in a sunlit chapel."
    record(body, executor.next(body, request, ctx, prompt), {"graph": graph, "recipe_manifest": manifest(graph)})
    response = executor.next(body, request, ctx, prompt)
    args = json.loads(response["output"][0]["arguments"])["arguments"]
    assert args["asset_bindings"] == {"reference.image": "angel"}
    assert args["overrides"] == {"video.prompt": prompt}
    assert args["capability"] == "image-to-video"
    record(body, response, {"workflow_id": "assistant-video"})
    response = executor.next(body, request, ctx, prompt)
    assert json.loads(response["output"][0]["arguments"])["operation"] == "queue_local_render"
    record(body, response, {"job_id": "confirmed-video-job"})
    assert final(executor.next(body, request, ctx, prompt))["workflow_execution"]["state"] == "queued"
    assert graph["reference"]["inputs"]["image"] == "sample.png"


def test_custom_video_recipe_offers_review_without_attempting_automatic_queue(tmp_path):
    graph = {"camera": {"class_type": "UnreviewedH3CameraEditor", "inputs": {"prompt": "Sample scene"}},
             "save": {"class_type": "SaveVideo", "inputs": {"video": ["camera", 0], "filename_prefix": "video"}}}
    executor = WorkflowExecutor(settings_for(tmp_path))
    body, ctx, request, prompt = {"input": []}, context(), "Generate a video", "An angel slowly spreading her wings in a sunlit chapel."
    record(body, executor.next(body, request, ctx, prompt), {"graph": graph, "recipe_manifest": manifest(graph)})
    response = executor.next(body, request, ctx, prompt)
    assert json.loads(response["output"][0]["arguments"])["operation"] == "prepare_workflow"
    record(body, response, {"workflow_id": "assistant-camera"})
    answer = final(executor.next(body, request, ctx, prompt))
    assert answer["workflow_execution"]["state"] == "awaiting_approval"
    assert answer["workflow_id"] == "assistant-camera"
    assert answer["generation_prompt"] == prompt
    assert "UnreviewedH3CameraEditor" in answer["reply"]


def test_executor_retries_inspection_once_but_never_retries_submission(tmp_path, flux_graph):
    executor = WorkflowExecutor(settings_for(tmp_path))
    body, ctx = {"input": []}, context()
    request, prompt = "Generate one image", "An angel standing in a courtyard."
    failure = {"error": "Connection refused", "error_code": "service_unavailable", "retryable": True}
    record(body, executor.next(body, request, ctx, prompt), failure)
    retry = executor.next(body, request, ctx, prompt)
    assert retry["output"][0]["type"] == "function_call"
    record(body, retry, failure)
    assert final(executor.next(body, request, ctx, prompt))["workflow_execution"]["state"] == "blocked"
    body = {"input": []}
    record(body, executor.next(body, request, ctx, prompt), {"graph": flux_graph, "recipe_manifest": manifest(flux_graph)})
    record(body, executor.next(body, request, ctx, prompt), {"workflow_id": "assistant-current"})
    record(body, executor.next(body, request, ctx, prompt), failure)
    assert final(executor.next(body, request, ctx, prompt))["workflow_execution"]["state"] == "blocked"


def test_executor_manual_review_and_distinct_shots_do_not_mix_subjects(tmp_path, flux_graph):
    executor = WorkflowExecutor(settings_for(tmp_path))
    ctx = {**context(), "allow_local_rendering": False}
    body = {"input": []}
    plan = {"shots": [{"id": "shot-1", "prompt": "An angel inside a sunlit chapel.", "reference_asset_ids": []},
                      {"id": "shot-2", "prompt": "A blue truck parked on a rainy street.", "reference_asset_ids": []}]}
    request = "Generate two images"
    record(body, executor.next(body, request, ctx, plan["shots"][0]["prompt"], plan), {"graph": flux_graph, "recipe_manifest": manifest(flux_graph)})
    for index, shot in enumerate(plan["shots"]):
        response = executor.next(body, request, ctx, plan["shots"][0]["prompt"], plan)
        call = json.loads(response["output"][0]["arguments"])
        assert call["operation"] == "prepare_workflow"
        assert call["arguments"]["brief_id"] == shot["id"]
        assert call["arguments"]["overrides"]["18:17.value"] == shot["prompt"]
        record(body, response, {"workflow_id": f"assistant-{index}"})
    answer = final(executor.next(body, request, ctx, plan["shots"][0]["prompt"], plan))
    assert answer["workflow_execution"]["state"] == "awaiting_approval"
    assert answer["workflow_id"] == "assistant-0"


def test_ambiguous_recipe_blocks_without_preparing_anything(tmp_path, flux_graph):
    executor = WorkflowExecutor(settings_for(tmp_path))
    graph = deepcopy(flux_graph)
    graph["18:4"]["inputs"]["text"] = "First description"
    graph["detail"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "Second description"}}
    graph["18:7"]["inputs"]["positive_detail"] = ["detail", 0]
    body, ctx = {"input": []}, context()
    record(body, executor.next(body, "Generate image", ctx, "An angel in a chapel."), {"graph": graph, "recipe_manifest": manifest(graph)})
    answer = final(executor.next(body, "Generate image", ctx, "An angel in a chapel."))
    assert answer["workflow_execution"]["error_code"] == "recipe_mapping_required"


def test_blocked_execution_is_saved_as_blocked_not_successful_reply(tmp_path):
    from darius_api.agent_harness import run_assistant_graph
    from darius_api.workflow_executor import final_response
    result = run_assistant_graph(settings_for(tmp_path), {"input": []}, "task", "project",
        lambda *a, **k: final_response("Register the base recipe first.", state="blocked", error_code="recipe_mapping_required"), None)
    assert result["task"]["state"] == "blocked"
    assert result["task"]["error_code"] == "recipe_mapping_required"


def test_protected_instructions_cannot_be_changed_through_a_graph_copy(tmp_path, flux_graph):
    from darius_api.comfy_assistant import ComfyAssistantTools
    defaults = tmp_path / "defaults"; defaults.mkdir()
    (defaults / "flux.json").write_text(json.dumps(flux_graph))
    settings = replace(settings_for(tmp_path), comfy_workflow_defaults_root=defaults)
    tools = ComfyAssistantTools(settings, None, None)
    tools.workflow_policy = {"enabled": True, "allowed_ids": ["flux.json"]}
    assert not tools.call({"operation": "inspect_workflow", "arguments": {"workflow_id": "flux.json"}}, 20).get("error")
    changed = deepcopy(flux_graph)
    changed["18:14"]["inputs"]["value"] = "Replace the real instructions."
    response = tools.call({"operation": "prepare_graph", "arguments": {"graph": changed, "name": "unsafe"}}, 20)
    assert "protected workflow instructions" in response["error"]
    response = tools.call({"operation": "prepare_workflow", "arguments": {"workflow_id": "flux.json", "name": "unsafe", "overrides": {"18:14.value": "Replace the real instructions."}}}, 20)
    assert "protected workflow instructions" in response["error"]


def test_registration_api_is_source_versioned_and_never_creates_jobs(tmp_path, flux_graph, monkeypatch):
    from fastapi.testclient import TestClient
    from darius_api.main import create_app
    from darius_api.comfy_assistant import ComfyAssistantTools
    defaults = tmp_path / "defaults"; defaults.mkdir()
    path = defaults / "flux.json"; path.write_text(json.dumps(flux_graph))
    definitions = tmp_path / "definitions"; definitions.mkdir()
    settings = replace(settings_for(tmp_path), comfy_workflow_defaults_root=defaults, workflow_definitions_dir=definitions)
    def inspect(_self, request, timeout):
        assert request["operation"] == "inspect_workflow"
        return {"recipe_manifest": register(settings, request["arguments"]["workflow_id"], flux_graph)}
    monkeypatch.setattr(ComfyAssistantTools, "call", inspect)
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/workflow-recipes/register", json={"workflow_id": "flux.json"})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["scene_slots"] == ["18:17.value"]
        saved = client.put("/api/v1/workflow-recipes/registration", json={"workflow_id": "flux.json", "source_digest": data["source_digest"], "roles": {"18:17.value": "scene"}})
        assert saved.status_code == 200
        invalid = client.put("/api/v1/workflow-recipes/registration", json={"workflow_id": "flux.json", "source_digest": data["source_digest"], "roles": {"18:14.value": "scene"}})
        assert invalid.status_code == 422
        assert client.post("/api/v1/workflow-recipes/register", json={"workflow_id": "../private.json"}).status_code == 422
        path.write_text(json.dumps({**flux_graph, "new": {"class_type": "PreviewAny", "inputs": {}}}))
        assert client.put("/api/v1/workflow-recipes/registration", json={"workflow_id": "flux.json", "source_digest": data["source_digest"], "roles": {}}).status_code == 409
        assert client.get("/api/v1/jobs").json() == []
        monkeypatch.setattr("darius_api.workflow_catalog.atomic_json", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
        assert client.post("/api/v1/workflow-recipes/refresh").status_code == 503


def test_corrupt_cache_is_ignored_and_role_changes_change_contract_digest(tmp_path, flux_graph):
    from darius_api.workflow_registration import cache_path
    defaults = tmp_path / "defaults"; defaults.mkdir()
    (defaults / "flux.json").write_text(json.dumps(flux_graph))
    settings = replace(settings_for(tmp_path), comfy_workflow_defaults_root=defaults)
    data = register(settings, "flux.json", flux_graph)
    changed = manifest(flux_graph, {"18:17.value": "preserve"})
    assert changed["contract_digest"] != data["contract_digest"]
    cache_path(settings, "flux.json").write_text("[]")
    assert registered(settings, "flux.json") is None
    assert compiled(settings, "flux.json") is None


@pytest.mark.parametrize("node", ["EmptyFlux2LatentImage", "Flux3LayoutPrompt", "CreateBoundingBoxes", "PreviewAny", "TextGenerate",
    "MiniMaxH3SigmaShift", "ModelAttentionBackend", "ImageScaleToTotalPixels", "H3LocalCameraEditor",
    "ShowText|pysssss", "ModelPreviewOverrideKJ"])
def test_audited_helpers_require_exact_local_origin_and_cannot_be_api_nodes(tmp_path, monkeypatch, node):
    from types import SimpleNamespace
    from darius_api import local_render
    from darius_api.providers import ProviderError
    graph = {"1": {"class_type": node, "inputs": {}}}
    contract = SimpleNamespace(execution_provider="local-comfyui", estimated_cost=0, source_asset_ids=[],
                               runtime_mapping=SimpleNamespace(api_format=True), enabled=True)
    info = {node: {"python_module": local_render.LOCAL_NODES[node]}}
    monkeypatch.setattr(local_render, "inspect_local_nodes", lambda *a: info)
    local_render.verify_local_graph(settings_for(tmp_path), contract, graph)
    info[node]["api_node"] = True
    with pytest.raises(ProviderError, match="not a verified local node"):
        local_render.verify_local_graph(settings_for(tmp_path), contract, graph)
    info[node] = {"python_module": "custom_nodes.spoofed"}
    with pytest.raises(ProviderError, match="not a verified local node"):
        local_render.verify_local_graph(settings_for(tmp_path), contract, graph)


def test_unusable_base_blocks_before_any_model_tokens(tmp_path, monkeypatch):
    from darius_api.providers import OpenAIPlannerProvider
    from darius_api.comfy_assistant import TOOL_DEFINITIONS
    from darius_api.agent_harness import parse_assistant_answer
    provider = OpenAIPlannerProvider(settings_for(tmp_path))
    monkeypatch.setattr(provider, "ready", lambda: True)
    monkeypatch.setattr(provider, "_visual_brief_response", lambda *a, **k: pytest.fail("Unusable recipes must not spend brief tokens"))
    monkeypatch.setattr(provider, "_responses", lambda *a, **k: pytest.fail("Unusable recipes must not spend planning tokens"))
    ctx = {**context(), "assistant_conversation": True,
           "preferred_workflow": {"id": "flux.json", "execution_provider": "local-comfyui"},
           "workflow_policy": {"enabled": True, "instruction": "Use the base recipe."}}
    calls = []
    def tool(envelope, timeout):
        calls.append(envelope["operation"])
        assert envelope["operation"] == "inspect_workflow"
        return {"error": "Missing node", "error_code": "dependency_unavailable", "retryable": False}
    response = provider.plan(ctx, "Generate an image of an angel", tool_runner=tool, tool_definitions=TOOL_DEFINITIONS)
    assert calls == ["inspect_workflow"]
    assert parse_assistant_answer(response["output"])["workflow_execution"]["state"] == "blocked"


@pytest.mark.parametrize("pause_after", ["prepare_workflow", "queue_local_render"])
def test_api_executor_resumes_saved_steps_without_duplicate_jobs(tmp_path,monkeypatch,pause_after):
    graph={'1':{'class_type':'CLIPTextEncode','inputs':{'text':'Old example'}},
        '2':{'class_type':'KSampler','inputs':{'positive':['1',0]}},
        '3':{'class_type':'SaveImage','inputs':{'images':['2',0],'filename_prefix':'test'}}}
    settings=settings_for(tmp_path)
    executor=WorkflowExecutor(settings)
    ctx={**context(),'preferred_workflow_id':'base.json'}
    body={'input':[]};calls=[];prompt='A blue delivery truck parked beside a sunlit warehouse.'
    for _ in range(6):
        response=executor.next(body,'Generate one image',ctx,prompt)
        if response['output'][0]['type']=='message':
            answer=final(response);break
        operation=json.loads(response['output'][0]['arguments'])['operation']
        calls.append(operation)
        result={'graph':graph,'recipe_manifest':manifest(graph)} if operation=='inspect_workflow' else ({'workflow_id':'prepared-truck'} if operation=='prepare_workflow' else {'job_id':'confirmed-truck-job'})
        record(body,response,result)
        if operation==pause_after:
            # Persist tool receipts before simulating process loss; a new
            # executor must consume them rather than repeating the mutation.
            checkpoint=tmp_path/'checkpoint.json';checkpoint.write_text(json.dumps(body),encoding='utf-8')
            body=json.loads(checkpoint.read_text(encoding='utf-8'));executor=WorkflowExecutor(settings)
    else:pytest.fail('Executor did not finish')
    assert answer['workflow_execution']['job_ids']==['confirmed-truck-job']
    assert calls==['inspect_workflow','prepare_workflow','queue_local_render']
    assert graph['1']['inputs']['text']=='Old example'
