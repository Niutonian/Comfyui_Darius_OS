import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from darius_api import assistant_assets
from darius_api.assistant_assets import list_project_assets, view_project_assets, image_preview
from darius_api.comfy_assistant import ComfyAssistantTools, TOOL_DEFINITIONS
from darius_api.database import Asset, GenerationRecord
from darius_api.main import create_app
from darius_api.providers import OpenAIPlannerProvider, ComfyMcpProvider, ProviderError
from darius_api.workflow_catalog import discover_workflows, record_conversion, record_execution, workflow_source_path
from test_media_backend import settings_for, create_project


def test_langgraph_image_to_video_persists_reference_seed_name_and_completion(setup,monkeypatch):
    from darius_api.database import Message
    from darius_api.providers import ProviderResult
    from darius_api.services import JobWorker,enqueue_request,register_workflows
    from darius_api.workflows import WorkflowContract
    settings,app,client,project,asset,calls=setup
    cid=client.post(f'/api/v1/projects/{project}/conversations',json={}).json()['id']
    mid=client.post(f'/api/v1/conversations/{cid}/messages',json={'role':'user','content':'Historical Homecoming render',
        'metadata':{'task':{'engine':'langgraph','state':'queued'}}}).json()['id']
    graph=json.loads(json.dumps(GRAPH));graph['3']['inputs']['seed']=42
    path=settings.data_dir/'reviewed-video.json';path.write_text(json.dumps(graph),encoding='utf-8')
    contract=WorkflowContract.model_validate({'id':'reviewed-homecoming','name':'Homecoming','version':'1',
        'capability':'image-to-video','execution_provider':'local-comfyui','workflow_reference':str(path),
        'required_inputs':[{'key':'seed','type':'integer','required':False,'default':42,'maps_to':{'slot':'3.seed'}}],
        'output':{'kind':'video','count':1},'runtime_mapping':{'api_format':True,'filename_prefix_slot':'2.filename_prefix'},
        'source_asset_ids':[asset['id']],'requires_approval':True})
    app.state.registry.add(contract);register_workflows(app.state.session_factory,app.state.registry)
    job=enqueue_request(app.state.session_factory,app.state.registry,project,contract.id,'Homecoming dragon moves gently',{},True)
    with app.state.session_factory.begin() as session:
        saved=session.get(__import__('darius_api.database',fromlist=['Job']).Job,job.id)
        saved.input_payload={**saved.input_payload,'local_render_message_id':mid}
    output=settings.data_dir/'mock-video.mp4';output.write_bytes(b'mock video output')
    class Renderer:
        def execute(self,contract,inputs,project_id,job_id):
            assert contract.source_asset_ids==[asset['id']]
            return ProviderResult('mock',(output,),{},mocked=True)
    JobWorker(app.state.session_factory,app.state.registry,settings,Renderer()).run_once(job.id)
    result=client.get(f'/api/v1/jobs/{job.id}').json()
    assert result['status']=='completed',result
    generated=client.get(f"/api/v1/assets/{result['output_asset_ids'][0]}").json()
    assert generated['parent_asset_ids']==[asset['id']]
    assert generated['metadata']['generation_seeds']=={'3.seed':42}
    assert 'homecoming' in generated['metadata']['display_name'].casefold()
    with app.state.session_factory() as session:assert session.get(Message,mid).metadata_json['task']['state']=='completed'


GRAPH = {"1": {"class_type": "LoadImage", "inputs": {"image": "old-example.png"}},
         "2": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "original", "video": ["3", 0]}},
         "3": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"image": ["1", 0], "prompt": "original"}}}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    definitions = tmp_path / "definitions"
    shutil.copytree(settings.workflow_definitions_dir, definitions)
    library = tmp_path / "workflows"
    library.mkdir()
    (library / "mcp_minimax_i2v.json").write_text(json.dumps(GRAPH))
    # Automatic recipes are defaults-folder bases, not custom/generated drafts.
    settings = replace(settings, workflow_definitions_dir=definitions, comfy_workflow_root=library,
                       comfy_workflow_defaults_root=library)
    calls = []
    def run(self, args, timeout):
        calls.append(args)
        if "get" in args:
            Path(args[args.index("--out") + 1]).write_text(json.dumps(GRAPH))
        if "upload" in args:
            return {"data": {"uploads": [{"cloud_name": Path(args[args.index("upload") + 1]).name, "subfolder": "references", "type": "input"}]}}
        return {"data": {"valid": True}}
    monkeypatch.setattr(ComfyMcpProvider, "_run", run)
    # Uploaded test bytes are represented by the fake MCP server above.
    monkeypatch.setattr("darius_api.comfy_preflight._visible_in_comfy", lambda *args: None)
    app = create_app(settings)
    with TestClient(app) as client:
        project = create_project(client)
        asset = client.post("/api/v1/assets/upload", data={"project_id": project}, files={"file": ("dragon.png", b"image-test", "image/png")}).json()
        yield settings, app, client, project, asset, calls


def test_image_lookup_is_project_scoped_and_preview_has_pixels_without_file_paths(setup, monkeypatch):
    settings, app, client, project, asset, calls = setup
    other = create_project(client, "Other")
    assert list_project_assets(app.state.session_factory, project, query="dragon", kind="image")["assets"][0]["id"] == asset["id"]
    assert list_project_assets(app.state.session_factory, other)["assets"] == []
    monkeypatch.setattr(assistant_assets.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=b"\xff\xd8preview"))
    result = view_project_assets(app.state.session_factory, settings, project, [asset["id"]])
    assert result["_image_content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    assert str(settings.data_dir) not in json.dumps(result)
    with pytest.raises(ProviderError, match="belong"):
        view_project_assets(app.state.session_factory, settings, other, [asset["id"]])
    with app.state.session_factory.begin() as session:
        stored = session.get(Asset, asset["id"])
        stored.path = str(settings.repository_root / "README.md")
    with pytest.raises(ProviderError, match="managed storage"):
        view_project_assets(app.state.session_factory, settings, project, [asset["id"]])


def test_binding_replaces_template_image_and_survives_later_edits(setup):
    settings, app, client, project, asset, calls = setup
    tool = ComfyAssistantTools(settings, app.state.registry, app.state.session_factory, project_id=project)
    args = {"workflow_id": "mcp_minimax_i2v.json", "name": "Animate dragon", "output_kind": "video", "capability": "image-to-video",
            "overrides": {"3.prompt": "The dragon breathes gently"}, "asset_bindings": {"1.image": asset["id"]}}
    result = tool.call({"operation": "prepare_workflow", "arguments_json": json.dumps(args)})
    assert "error" not in result, result
    contract = app.state.registry.get(result["workflow_id"])
    graph = json.loads(Path(contract.workflow_reference).read_text())
    assert graph["1"]["inputs"]["image"] == f"references/darius-{asset['id']}.png"
    assert contract.source_asset_ids == [asset["id"]]
    next_turn = ComfyAssistantTools(settings, app.state.registry, app.state.session_factory, project_id=project)
    edited = next_turn.call({"operation": "prepare_workflow", "arguments_json": json.dumps({"workflow_id": contract.id, "name": "Slower motion", "output_kind": "video", "capability": "image-to-video", "overrides": {"3.prompt": "Slow movement"}})})
    assert "error" not in edited, edited
    assert app.state.registry.get(edited["workflow_id"]).source_asset_ids == [asset["id"]]
    assert json.loads((settings.comfy_workflow_root / "mcp_minimax_i2v.json").read_text())["1"]["inputs"]["image"] == "old-example.png"
    proposal = client.post(f"/api/v1/workflows/{contract.id}/propose", json={"project_id": project, "request_text": "Animate it", "inputs": {}}).json()
    approved = client.post(f"/api/v1/action-plans/{proposal['id']}/approve").json()
    with app.state.session_factory() as session:
        assert session.scalar(select(GenerationRecord).where(GenerationRecord.job_id == approved["job_id"])).source_asset_ids == [asset["id"]]


def test_binding_rejects_cross_project_assets_before_upload(setup):
    settings, app, client, project, asset, calls = setup
    other = create_project(client, "Other")
    tool = ComfyAssistantTools(settings, app.state.registry, app.state.session_factory, project_id=other)
    result = tool.call({"operation": "prepare_graph", "arguments_json": json.dumps({"graph": GRAPH, "name": "Wrong reference", "asset_bindings": {"1.image": asset["id"]}})})
    assert "error" in result
    assert all("upload" not in call for call in calls)


def test_video_draft_does_not_keep_unbound_template_reference(setup):
    settings, app, client, project, asset, calls = setup
    graph = {**GRAPH, "4": {"class_type": "LoadImage", "inputs": {"image": "unrelated-template.png"}}}
    tool = ComfyAssistantTools(settings, app.state.registry, app.state.session_factory, project_id=project)
    result = tool.call({"operation": "prepare_graph", "arguments_json": json.dumps({"graph": graph, "name": "Only one reference", "output_kind": "video", "asset_bindings": {"1.image": asset["id"]}})})
    assert "Unbound template image inputs: 4.image" in result["error"]
    assert all("upload" not in call for call in calls)


def test_visual_tool_result_becomes_multimodal_input_not_json_text(tmp_path, monkeypatch):
    provider = OpenAIPlannerProvider(replace(settings_for(tmp_path), openai_api_key="test", openai_planner_model="test"))
    count = 0
    def response(body, timeout):
        nonlocal count
        count += 1
        if count == 1:
            return {"output": [{"type": "function_call", "call_id": "view-1", "name": "comfyui", "arguments": json.dumps({"operation": "view_assets", "arguments_json": '{"asset_ids":["image-1"]}'})}]}
        assert body["input"][-1]["content"][1]["type"] == "input_image"
        assert body["input"][-1]["content"][1]["image_url"] == "data:image/jpeg;base64,/9g="
        assert "base64" not in body["input"][-2]["output"]
        return {"output": []}
    monkeypatch.setattr(provider, "_responses", response)
    provider.plan({"assistant_conversation": True}, "Look at this image", tool_definitions=TOOL_DEFINITIONS,
                  tool_runner=lambda *args: {"viewed_asset_ids": ["image-1"], "_image_content": [{"type": "input_text", "text": "Image image-1"}, {"type": "input_image", "image_url": "data:image/jpeg;base64,/9g="}]})
    assert count == 2


def test_workflow_ranking_prefers_requested_provider_and_image_inputs(setup):
    settings, *_ = setup
    (settings.comfy_workflow_root / "minimax_t2v.json").write_text(json.dumps({"1": {"class_type": "SaveVideo", "inputs": {}}}))
    (settings.comfy_workflow_root / "ltx_i2v.json").write_text(json.dumps(GRAPH))
    result = discover_workflows(settings, query="minimax", output_kind="video", source_kind="image")
    assert result["workflows"][0]["workflow_id"] == "mcp_minimax_i2v.json"
    assert result["workflows"][0]["requires_inspection"]
    assert result["workflows"][-1]["workflow_id"] == "minimax_t2v.json"
    record_conversion(settings, "mcp_minimax_i2v.json", False)
    ranked = discover_workflows(settings, query="minimax", output_kind="video", source_kind="image")
    assert ranked["workflows"][0]["workflow_id"] == "ltx_i2v.json"
    assert ranked["workflows"][-1]["conversion_status"] == "conversion failed"


def test_workflow_compatibility_accumulates_render_evidence(setup):
    settings, *_ = setup
    workflow_id = "mcp_minimax_i2v.json"
    record_conversion(settings, workflow_id, True)
    record_execution(settings, workflow_id, True)
    record_execution(settings, workflow_id, False, "synthetic out of VRAM")

    result = discover_workflows(settings, query="minimax", output_kind="video", source_kind="image")
    candidate = next(item for item in result["workflows"] if item["workflow_id"] == workflow_id)
    compatibility = candidate["compatibility"]
    assert compatibility["successful_renders"] == 1
    assert compatibility["failed_renders"] == 1
    assert compatibility["last_render_status"] == "failed"
    assert compatibility["last_error"] == "synthetic out of VRAM"
    assert any("Render-proven locally" in reason for reason in candidate["reasons"])


def test_darius_defaults_are_discovered_before_custom_workflows(setup, tmp_path):
    settings, *_ = setup
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    default = defaults / "Darius_minimax_t2v.json"
    default.write_text(json.dumps({"1": {"class_type": "SaveVideo", "inputs": {}}}))
    (settings.comfy_workflow_root / "custom_minimax_t2v.json").write_text(json.dumps({"1": {"class_type": "SaveVideo", "inputs": {}}}))
    settings = replace(settings, comfy_workflow_defaults_root=defaults)

    result = discover_workflows(settings, query="minimax", output_kind="video", source_kind="none")

    assert result["workflows"][0]["workflow_id"] == "Darius_minimax_t2v.json"
    assert "Managed Darius default" in result["workflows"][0]["reasons"][-1]
    assert workflow_source_path(settings, "Darius_minimax_t2v.json")[1] == default.resolve()


def test_visual_reply_preserves_viewed_and_bound_asset_ids_in_history(setup,monkeypatch):
    from test_assistant import FakeAssistant
    settings,app,client,project,asset,calls=setup
    monkeypatch.setattr(assistant_assets,'image_preview',lambda *a:{'type':'input_image','image_url':'data:image/jpeg;base64,/9g='})
    provider=FakeAssistant();app.state.planner_provider=provider
    chat=client.post(f'/api/v1/projects/{project}/conversations',json={}).json()
    base=f"/api/v1/conversations/{chat['id']}"
    user=client.post(base+'/messages',json={'role':'user','content':'Develop an animation prompt','metadata':{'asset_ids':[asset['id']]}}).json()
    reply=client.post(base+'/reply',json={'message_id':user['id']})
    assert reply.status_code==200,reply.text
    assert provider.calls[0][0]['attached_asset_ids']==[asset['id']]
    assert reply.json()['metadata']['task']['engine']=='creative-helper'
    assert 'base64' not in reply.text
    assert client.get(base+'/messages').json()[0]['metadata']['asset_ids']==[asset['id']]
    assert client.get(f'/api/v1/jobs?project_id={project}').json()==[]
