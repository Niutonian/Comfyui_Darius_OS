import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from darius_api.chat_labels import intent_label, output_label, readable_name, render_receipt
from darius_api.conversation_intent import resolve_production_target
from darius_api.database import Job, Message
from darius_api.main import create_app
from darius_api.visual_plan import normalize_plan
from darius_api.workflow_executor import WorkflowExecutor
from test_assistant import FakeAssistant
from test_media_backend import create_project, settings_for


def chat(client, project, text, metadata=None):
    cid = client.post(f"/api/v1/projects/{project}/conversations", json={}).json()["id"]
    base = f"/api/v1/conversations/{cid}"
    user = client.post(base + "/messages", json={"role": "user", "content": text, "metadata": metadata or {}}).json()
    return base, user


def production_context():
    return {"scenes": [{"id": "s1", "number": 1, "title": "Forest"}, {"id": "s2", "number": 2, "title": "Harbour"}],
            "shots": [{"id": "a", "number": 1, "scene_id": "s1"}, {"id": "b", "number": 1, "scene_id": "s2"}],
            "characters": [{"id": "tommy", "name": "Tommy Nolan", "canonical_prompt": "A young boy in an ochre jacket."}]}


def test_shot_numbers_need_scene_when_ambiguous_and_explicit_choice_overrides_focus():
    context = production_context()
    with pytest.raises(HTTPException, match="Which scene"):
        resolve_production_target(context, "Generate shot 1")
    context["project_memory"] = {"scene_id": "s1", "shot_id": "a"}
    resolve_production_target(context, "Generate Tommy Nolan in scene 2 shot 1")
    assert context["project_memory"]["shot_id"] == "b"
    assert context["shots"] == [{"id": "b", "number": 1, "scene_id": "s2"}]
    assert context["resolved_intent"]["subject_ids"] == ["tommy"]
    assert intent_label(context, "unrelated fallback") == "Tommy Nolan — Harbour — Shot 1"


def test_named_subject_cannot_be_replaced_by_template_subject():
    context = production_context()
    resolve_production_target(context, "Generate an image of Tommy Nolan")
    with pytest.raises(ValueError, match="Tommy Nolan"):
        normalize_plan({"generation_prompt": "A hedgehog in a garden."}, context, "Generate an image of Tommy Nolan")
    plan = normalize_plan({"generation_prompt": "Tommy Nolan beside a forest path."}, context, "Generate an image of Tommy Nolan")
    assert plan["shots"][0]["subject_ids"] == ["tommy"]
    assert plan["shots"][0]["subjects"][0]["canonical_prompt"] == context["characters"][0]["canonical_prompt"]


def test_chat_proposed_shot_does_not_require_a_saved_bible_record():
    context = {"messages": [{"role": "assistant", "content": "Shot 1: Tommy stands beside the forest."}]}
    resolve_production_target(context, "Generate shot 1")
    assert context["resolved_intent"]["output_count"] == 1


def test_multiple_explicit_targets_do_not_hide_the_second_scene():
    context = production_context()
    context["project_memory"] = {"scene_id": "s1", "shot_id": "a"}
    resolve_production_target(context, "Generate two images: scene 1 shot 1 and scene 2 shot 1")
    assert len(context["scenes"]) == 2 and len(context["shots"]) == 2
    assert context["project_memory"]["scene_id"] is None


def test_multi_shot_subjects_stay_separate():
    context = production_context()
    context["characters"].append({"id": "alice", "name": "Alice", "canonical_prompt": "A woman in a blue coat."})
    resolve_production_target(context, "Generate two images, Tommy Nolan alone and Alice alone")
    plan = normalize_plan({"shots": [{"prompt": "Tommy Nolan alone in the forest."}, {"prompt": "Alice alone on the beach."}]}, context, "Generate two images")
    assert plan["shots"][0]["subject_ids"] == ["tommy"]
    assert plan["shots"][1]["subject_ids"] == ["alice"]


@pytest.mark.parametrize("states, expected", [(["failed", "running"], "running"), (["completed", "queued"], "queued"), (["completed", "failed"], "failed"), (["completed", "completed"], "completed")])
def test_task_state_is_not_finished_while_a_batch_is_still_working(states, expected):
    from darius_api.task_lifecycle import render_state
    assert render_state(states) == expected


def test_worker_updates_the_saved_user_and_assistant_lifecycle_together(tmp_path):
    from darius_api.services import update_agent_task
    app = create_app(settings_for(tmp_path), planner_provider=FakeAssistant())
    with TestClient(app) as client:
        project = create_project(client)
        base, user = chat(client, project, "Generate two images of a forest")
        with app.state.session_factory.begin() as session:
            source = session.get(Message, user["id"])
            source.metadata_json = {"task": {"engine": "langgraph"}, "local_render_job_ids": ["first", "second"]}
            session.add(Message(id="reply", conversation_id=source.conversation_id, role="assistant", content="Queued.", metadata_json={"reply_to": source.id}))
            for key, status in (("first", "failed"), ("second", "running")):
                session.add(Job(id=key, project_id=project, provider="local-comfyui", status=status, input_payload={"local_render_message_id": source.id, "render_name": "Forest"}, output_asset_ids=[]))
            session.flush()
            update_agent_task(session, session.get(Job, "second"))
        history = client.get(base + "/messages").json()
        assert all(item["metadata"]["task"]["state"] == "running" for item in history)
        assert history[-1]["metadata"]["task"]["job_ids"] == ["first", "second"]


def test_friendly_names_leave_identifiers_out_of_output_and_receipt():
    identifier = "3f6acde7-81fd-4a00-9b23-72aa99d1e0c3"
    assert identifier not in output_label("Tommy in the forest " + identifier, "image", 1)
    assert readable_name("tommy-forest-3f6acde7-01.png") == "Tommy-forest-01"
    receipt = render_receipt([{"job_id": identifier, "name": "Tommy — Forest", "status": "queued"}])
    assert "Tommy — Forest — queued" in receipt and identifier not in receipt


@pytest.mark.parametrize("clarification", ["scene 2", "scene two"])
def test_clarification_is_saved_and_focused_answer_continues_without_retyping(tmp_path, monkeypatch, clarification):
    provider = FakeAssistant()
    monkeypatch.setattr('darius_api.main.route_context', lambda *a: pytest.fail('Text chat must not route recipes'))
    with TestClient(create_app(settings_for(tmp_path), planner_provider=provider)) as client:
        project = create_project(client)
        for number in (1, 2):
            scene = client.post(f'/api/v1/projects/{project}/scenes', json={'number':number,'title':f'Scene {number}'}).json()
            client.post(f"/api/v1/scenes/{scene['id']}/shots", json={'number':1,'description':f'Subject in scene {number}'})
        base,user = chat(client,project,'Develop a prompt for shot 1')
        first=client.post(base+'/reply',json={'message_id':user['id']})
        assert first.status_code==200
        answer=client.post(base+'/messages',json={'role':'user','content':clarification}).json()
        second=client.post(base+'/reply',json={'message_id':answer['id']})
        assert second.status_code==200
        context,text=provider.calls[-1]
        assert text==clarification
        assert context['assistant_mode']=='creative-helper'
        assert any(m['content']=='Develop a prompt for shot 1' for m in context['messages'])
        assert {s['description'] for s in context['shots']}=={'Subject in scene 1','Subject in scene 2'}
        assert client.get(f'/api/v1/jobs?project_id={project}').json()==[]


def test_setup_recovery_reuses_saved_user_and_preserves_history(tmp_path, monkeypatch):
    provider=FakeAssistant()
    monkeypatch.setattr('darius_api.main.route_context',lambda *a: pytest.fail('Missing recipes must not block text chat'))
    app=create_app(settings_for(tmp_path),planner_provider=provider)
    with TestClient(app) as client:
        project=create_project(client)
        base,user=chat(client,project,'Generate an image of a blue truck')
        reply=client.post(base+'/reply',json={'message_id':user['id']})
        assert reply.status_code==200
        assert reply.json()['metadata']['task']['engine']=='creative-helper'
        assert client.post(base+f"/messages/{user['id']}/retry-preparation").status_code==409
        assert client.post(base+'/reply',json={'message_id':user['id']}).json()['id']==reply.json()['id']
        assert len(provider.calls)==1
        history=client.get(base+'/messages').json()
        assert len(history)==2 and history[0]['id']==user['id']
        assert client.get(f'/api/v1/jobs?project_id={project}').json()==[]


@pytest.mark.parametrize("status", ["queued", "running", "completed", "failed", "cancelled"])
def test_recovery_never_requeues_a_request_with_an_existing_job(tmp_path, monkeypatch, status):
    def unavailable(*args):
        raise HTTPException(422, "No base recipe. Refresh workflows.")
    monkeypatch.setattr("darius_api.main.route_context", unavailable)
    app = create_app(settings_for(tmp_path), planner_provider=FakeAssistant())
    with TestClient(app) as client:
        project = create_project(client)
        base, user = chat(client, project, "Generate an image of a blue truck")
        assert client.post(base + "/reply", json={"message_id": user["id"]}).status_code == 200
        with app.state.session_factory.begin() as session:
            source=session.get(Message,user['id'])
            latest=session.scalar(__import__('sqlalchemy').select(Message).where(Message.conversation_id==source.conversation_id,Message.role=='assistant'))
            latest.metadata_json={**latest.metadata_json,'recovery':{'can_retry':True}}
            session.add(Job(id="existing", project_id=project, provider="local-comfyui", status=status, input_payload={"local_render_message_id": user["id"]}))
        blocked = client.post(base + f"/messages/{user['id']}/retry-preparation")
        assert blocked.status_code == 409 and "already has renders" in blocked.text


def test_preflight_checks_references_before_any_visual_brief():
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": "sample.png"}},
             "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "A blue truck"}},
             "3": {"class_type": "KSampler", "inputs": {"positive": ["2", 0], "reference": ["1", 0]}},
             "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "sample"}}}
    problem = WorkflowExecutor.preflight({"graph": graph}, {"workflow_route": {"reference_asset_ids": []}}, "Edit an image")
    assert problem[1] == "missing_recipe_references"


@pytest.mark.parametrize("provider_class", ["OpenAIPlannerProvider", "DeepSeekPlannerProvider", "OllamaPlannerProvider", "LlamaCppPlannerProvider", "OpenCodePlannerProvider"])
def test_all_models_block_missing_references_without_brief_or_render(tmp_path, monkeypatch, provider_class):
    from darius_api import providers
    from darius_api.agent_harness import parse_assistant_answer
    from darius_api.comfy_assistant import TOOL_DEFINITIONS
    provider = getattr(providers, provider_class)(settings_for(tmp_path))
    monkeypatch.setattr(provider, "ready", lambda: True)
    for hook in ("_prepare_gpu", "_release_gpu"):
        if hasattr(provider, hook):
            monkeypatch.setattr(provider, hook, lambda: None)
    monkeypatch.setattr(provider, "_responses", lambda *a, **k: pytest.fail("No model turn is needed for missing references"))
    monkeypatch.setattr(provider, "_visual_brief_response", lambda *a, **k: pytest.fail("Brief must wait for preflight"))
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": "sample.png"}},
             "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "A blue truck"}},
             "3": {"class_type": "KSampler", "inputs": {"positive": ["2", 0], "reference": ["1", 0]}},
             "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "sample"}}}
    calls = []
    def tool(envelope, timeout):
        calls.append(envelope["operation"])
        assert envelope["operation"] == "inspect_workflow"
        return {"graph": deepcopy(graph)}
    context = {"assistant_conversation": True, "preferred_workflow_id": "image-edit.json",
               "preferred_workflow": {"id": "image-edit.json", "execution_provider": "local-comfyui"},
               "workflow_policy": {"enabled": True, "instruction": "Use the selected recipe."},
               "workflow_route": {"reference_asset_ids": []}}
    result = provider.plan(context, "Generate an image of a blue truck", tool_runner=tool, tool_definitions=TOOL_DEFINITIONS)
    answer = parse_assistant_answer(result["output"])
    assert answer["workflow_execution"]["error_code"] == "missing_recipe_references"
    assert calls == ["inspect_workflow"]
