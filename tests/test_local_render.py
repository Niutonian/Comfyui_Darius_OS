"""Current chat denial and retained authorization of already persisted jobs.

Legacy jobs are seeded as database fixtures, not submitted through retired chat
routes. The supported Canvas Generate lifecycle is covered in test_canvas,
test_moss_workspace, test_canvas_h3 and test_job_recovery.
"""
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from darius_api import local_render
from darius_api.comfy_assistant import ComfyAssistantTools
from darius_api.database import Job, Message, GenerationRecord
from darius_api.main import create_app
from darius_api.providers import ComfyMcpProvider, ProviderError, ProviderResult
from darius_api.services import JobWorker, enqueue_request, register_workflows
from darius_api.workflows import WorkflowContract
from offline_fixtures import offline_definitions
from test_media_backend import settings_for, create_project
from test_comfy_assistant import GRAPH


@pytest.fixture
def local_setup(tmp_path, monkeypatch):
    settings = replace(settings_for(tmp_path), workflow_definitions_dir=offline_definitions(tmp_path))
    launched=[]
    monkeypatch.setattr(local_render,'launch_local_job',lambda settings,job_id:launched.append(job_id))
    monkeypatch.setattr(local_render,'inspect_local_nodes',lambda settings,names=None:{
        name:{'python_module':module} for name,module in local_render.LOCAL_NODES.items()})
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:io.BytesIO(b'{"queue_running":[],"queue_pending":[]}'))
    app=create_app(settings)
    with TestClient(app) as client:
        project=create_project(client)
        cid=client.post(f'/api/v1/projects/{project}/conversations',json={}).json()['id']
        message=client.post(f'/api/v1/conversations/{cid}/messages',json={'role':'user','content':'Generate three images',
            'metadata':{'task':{'engine':'langgraph','state':'queued'}}}).json()['id']
        graph_path=settings.data_dir/'historical-fixture.json'
        graph_path.write_text(json.dumps(GRAPH),encoding='utf-8')
        contract=WorkflowContract.model_validate({'id':'assistant-historical-fixture','name':'Historical still','version':'1',
            'capability':'text-to-image','execution_provider':'local-comfyui','workflow_reference':str(graph_path),
            'required_inputs':[],'output':{'kind':'image','count':1},
            'runtime_mapping':{'api_format':True,'filename_prefix_slot':'2.filename_prefix'},'requires_approval':True,'project_id':project})
        app.state.registry.add(contract);register_workflows(app.state.session_factory,app.state.registry)
        bridge=ComfyAssistantTools(settings,app.state.registry,app.state.session_factory,project_id=project,message_id=message)
        yield settings,app,client,project,cid,message,bridge,contract,launched


def persisted_auto_job(fixture, identifier='historical-job'):
    """Represent an approved job saved before chat execution was retired."""
    settings,app,client,project,cid,message,bridge,contract,launched=fixture
    directory=settings.data_dir/'jobs'/identifier;directory.mkdir(parents=True)
    snapshot=directory/'local-graph.json';snapshot.write_bytes(Path(contract.workflow_reference).read_bytes())
    saved=contract.model_copy(update={'workflow_reference':str(snapshot)})
    with app.state.session_factory.begin() as session:
        session.add(Job(id=identifier,project_id=project,provider='local-comfyui',status='queued',output_asset_ids=[],
            input_payload={'workflow_id':contract.id,'inputs':{},'approved':True,'approval_source':'project_local_rendering',
                'local_render_message_id':message,'local_render_contract':saved.model_dump(),
                'local_graph_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest()}))
        session.flush()
        session.add(GenerationRecord(id=identifier+'-generation',job_id=identifier,workflow_definition_id=contract.id,
            prompt='Historical still',parameters={},source_asset_ids=[],provider_response_metadata={},estimated_cost=0))
    return identifier


@pytest.mark.parametrize('enabled',[False,True])
@pytest.mark.parametrize('operation',['prepare_graph','prepare_workflow','queue_local_render','upload_asset',
    'validate_graph','create_character','create_scene','create_shot','rename_asset'])
def test_chat_cannot_mutate_or_queue_even_with_standing_permission(local_setup,enabled,operation):
    settings,app,client,project,cid,message,bridge,contract,launched=local_setup
    client.post(f'/api/v1/projects/{project}/local-rendering',json={'enabled':enabled})
    before=set(settings.workflow_definitions_dir.rglob('*'))
    for envelope in [{'operation':operation,'arguments':{'workflow_id':contract.id,'graph':GRAPH,'name':'Forged'}},
                     {'operation':operation,'arguments_json':'malformed'}]:
        for _ in range(2):
            result=bridge.call(envelope)
            assert result['error_code']=='chat_text_only' and result['retryable'] is False
    assert client.get(f'/api/v1/jobs?project_id={project}').json()==[]
    assert set(settings.workflow_definitions_dir.rglob('*'))==before
    assert launched==[]


@pytest.mark.parametrize('text',['Generate three separate images','ok, proceed','Generate 30 images',
    'Generate three images: first a person, second a planet, third a ship','Generate three videos'])
def test_retired_direct_queue_cannot_bypass_chat_capability(local_setup,text):
    settings,app,client,project,cid,message,bridge,contract,launched=local_setup
    client.post(f'/api/v1/projects/{project}/local-rendering',json={'enabled':True})
    with app.state.session_factory.begin() as session:session.get(Message,message).content=text
    with pytest.raises(ProviderError):
        local_render.queue_local_render(settings,app.state.registry,app.state.session_factory,project,message,contract.id)
    assert client.get(f'/api/v1/jobs?project_id={project}').json()==[] and not launched


def test_permission_is_persistent_project_scoped_and_not_tool_editable(local_setup):
    settings,app,client,project,cid,message,bridge,contract,launched=local_setup
    path=f'/api/v1/projects/{project}/local-rendering'
    assert client.get(path).json()=={'enabled':False}
    assert client.post(path,json={'enabled':'true'}).status_code==422
    assert client.post(path,json={'enabled':True}).json()=={'enabled':True}
    other=create_project(client,'Other')
    assert client.get(f'/api/v1/projects/{other}/local-rendering').json()=={'enabled':False}
    with TestClient(create_app(settings)) as restarted:assert restarted.get(path).json()=={'enabled':True}


@pytest.mark.parametrize('change',['revoked','tampered','custom_module'])
def test_historical_worker_rechecks_permission_hash_and_node_origin(local_setup,monkeypatch,change):
    settings,app,client,project,cid,message,bridge,contract,launched=local_setup
    client.post(f'/api/v1/projects/{project}/local-rendering',json={'enabled':True})
    job_id=persisted_auto_job(local_setup)
    if change=='revoked':client.post(f'/api/v1/projects/{project}/local-rendering',json={'enabled':False})
    elif change=='tampered':(settings.data_dir/'jobs'/job_id/'local-graph.json').write_text('{}')
    else:monkeypatch.setattr(local_render,'inspect_local_nodes',lambda *a,**k:{'SaveImage':{'python_module':'custom_nodes.external'}})
    class NeverRender:
        def execute(self,*args,**kwargs):pytest.fail('Unauthorized historical job must not execute')
    JobWorker(app.state.session_factory,app.state.registry,settings,NeverRender()).run_once(job_id)
    job=client.get(f'/api/v1/jobs/{job_id}').json()
    assert job['status']=='failed' and job['error_code']=='ProviderError'


@pytest.mark.parametrize('automatic',[False,True])
@pytest.mark.parametrize('linked',[False,True])
def test_worker_distinguishes_manual_approval_from_standing_permission(local_setup,automatic,linked):
    settings,app,client,project,cid,message,bridge,contract,launched=local_setup
    if automatic:
        client.post(f'/api/v1/projects/{project}/local-rendering',json={'enabled':True})
        job_id=persisted_auto_job(local_setup)
    else:job_id=enqueue_request(app.state.session_factory,app.state.registry,project,contract.id,'Reviewed still',{},True).id
    if linked:
        with app.state.session_factory.begin() as session:
            job=session.get(Job,job_id);job.input_payload={**job.input_payload,'local_render_message_id':message}
    approvals=[]
    class Renderer(ComfyMcpProvider):
        def execute(self,contract,inputs,project_id,job_id,*,manual_approval=False):
            approvals.append(manual_approval);return ProviderResult(None,(),{},mocked=True)
    JobWorker(app.state.session_factory,app.state.registry,settings,Renderer(settings)).run_once(job_id)
    assert approvals==[not automatic]


def test_worker_only_claims_requested_job_and_never_replays_completion(local_setup):
    settings,app,client,project,cid,message,bridge,contract,launched=local_setup
    client.post(f'/api/v1/projects/{project}/local-rendering',json={'enabled':True})
    target=persisted_auto_job(local_setup,'target');other=persisted_auto_job(local_setup,'other')
    calls=[]
    class Renderer:
        def execute(self,contract,inputs,project_id,job_id):calls.append(job_id);return ProviderResult(None,(),{},mocked=True)
    worker=JobWorker(app.state.session_factory,app.state.registry,settings,Renderer())
    assert worker.run_once(target)==target
    assert worker.run_once(target) is None
    assert calls==[target] and client.get(f'/api/v1/jobs/{other}').json()['status']=='queued'


@pytest.mark.parametrize('name',['H3ModelLoaderAny','H3ClipLoaderAny','H3Keyframes','H3ConditionStrength','H3LoraStack'])
def test_verified_h3_helpers_are_accepted_for_persisted_jobs(local_setup,name):
    settings,app,client,project,cid,message,bridge,contract,launched=local_setup
    local_render.verify_local_graph(settings,contract,{'1':{'class_type':name,'inputs':{}}})


@pytest.mark.parametrize('metadata',[{'python_module':'custom_nodes.unknown'},
    {'python_module':'custom_nodes.ComfyUI-H3-Multishot','api_node':True}])
def test_h3_origin_and_external_flag_are_still_checked(local_setup,monkeypatch,metadata):
    settings,app,client,project,cid,message,bridge,contract,launched=local_setup
    monkeypatch.setattr(local_render,'inspect_local_nodes',lambda *a:{'H3Keyframes':metadata})
    with pytest.raises(ProviderError,match='not a verified local node'):
        local_render.verify_local_graph(settings,contract,{'1':{'class_type':'H3Keyframes','inputs':{}}})


@pytest.mark.parametrize('name',['BFLFluxPro','HTTPNode','UnreviewedCustomNode'])
def test_external_and_unknown_graphs_fail_authorization(local_setup,name):
    settings,app,client,project,cid,message,bridge,contract,launched=local_setup
    with pytest.raises(ProviderError,match='unverified or external'):
        local_render.verify_local_graph(settings,contract,{'1':{'class_type':name,'inputs':{}}})
