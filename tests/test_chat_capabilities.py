"""Conversation execution is retired; board workers retain their own authorization.

These regressions supplement the retained legacy execution tests. Existing job
execution/recovery and immutable board generation are covered by the worker,
Canvas and creative-helper tests rather than restoring a chat queue fixture.
"""
from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from darius_api import local_render
from darius_api.comfy_assistant import ComfyAssistantTools
from darius_api.database import Job, ActionPlan
from darius_api.main import create_app
from darius_api.providers import ProviderError, ComfyMcpProvider
from darius_api.services import create_action_plan, approve_action_plan, RequestError
from test_media_backend import settings_for, create_project


@pytest.mark.parametrize("operation", ["prepare_graph","prepare_workflow","queue_local_render","upload_asset","validate_graph","create_character","create_scene","create_shot","update_shot","rename_asset","inspect_workflow"])
@pytest.mark.parametrize("enabled", [False, True])
def test_chat_dispatcher_has_no_mutation_or_preparation_capability(tmp_path,monkeypatch,operation,enabled):
    settings=settings_for(tmp_path)
    def forbidden(*a,**k):pytest.fail("Text-only chat reached a runtime/preparation tool")
    monkeypatch.setattr(ComfyMcpProvider,"_run",forbidden)
    with TestClient(create_app(settings)) as client:
        project=create_project(client)
        client.post(f"/api/v1/projects/{project}/local-rendering",json={"enabled":enabled})
        cid=client.post(f"/api/v1/projects/{project}/conversations",json={}).json()['id']
        mid=client.post(f"/api/v1/conversations/{cid}/messages",json={"role":"user","content":"Generate three images now", "metadata":{"origin":"board","capabilities":["queue_local_render"]}}).json()['id']
        bridge=ComfyAssistantTools(settings,client.app.state.registry,client.app.state.session_factory,project_id=project,message_id=mid)
        result=bridge.call({"operation":operation,"arguments":{"workflow_id":"forged","graph":{}}})
        assert result['error_code']=='chat_text_only' and not result['retryable']
        with pytest.raises(ProviderError,match="Chat cannot"):
            bridge._call(operation,{},1)
        automatic=bridge.finish_auto_render('forged')
        assert automatic is None or automatic.get('error_code')=='chat_text_only'
        with client.app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Job))==0


def test_direct_legacy_queue_and_unsubmitted_chat_plans_are_blocked(tmp_path):
    settings=settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        project=create_project(client);cid=client.post(f"/api/v1/projects/{project}/conversations",json={}).json()['id']
        mid=client.post(f"/api/v1/conversations/{cid}/messages",json={"role":"user","content":"Generate"}).json()['id']
        app=client.app
        with pytest.raises(ProviderError,match="Chat develops"):
            local_render.queue_local_render(settings,app.state.registry,app.state.session_factory,project,mid,'forged')
        with pytest.raises(RequestError,match="Use in board"):
            create_action_plan(app.state.session_factory,app.state.registry,project,'forged','Generate',{},cid,mid)
        workflow=next(iter(app.state.registry.enabled()))
        with app.state.session_factory.begin() as session:
            session.add(ActionPlan(id='old-plan',project_id=project,conversation_id=cid,workflow_definition_id=workflow.id,request_text='Generate',provider='local-comfyui',inputs={},expected_output={'source_message_id':mid}))
        with pytest.raises(RequestError,match="Unsubmitted chat proposals"):
            approve_action_plan(app.state.session_factory,app.state.registry,'old-plan')
        with app.state.session_factory.begin() as session:
            session.add(Job(id='existing-job',project_id=project,provider='local-comfyui',status='queued',input_payload={}))
            plan=session.get(ActionPlan,'old-plan');plan.state='queued';plan.job_id='existing-job'
        assert approve_action_plan(app.state.session_factory,app.state.registry,'old-plan').job_id=='existing-job'
        assert client.get(f"/api/v1/jobs?project_id={project}").json()[0]['status']=='queued'


def test_non_loopback_server_cannot_be_classified_as_local(tmp_path):
    settings=replace(settings_for(tmp_path),comfyui_base_url="http://external.example:8188")
    with pytest.raises(ProviderError,match="loopback"):
        local_render.inspect_local_nodes(settings)
