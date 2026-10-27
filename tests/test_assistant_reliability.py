"""Offline creative journey and ownership regression checks; no paid API calls."""
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from darius_api.main import create_app
from darius_api.database import Message, Asset
from darius_api.comfy_assistant import ComfyAssistantTools
from darius_api.task_control import check_task_control, TaskStopped, recover_interrupted_tasks
from darius_api.assistant_context import workflow_available
from test_assistant import FakeAssistant
from test_media_backend import settings_for, create_project


def conversation(client, project):
    cid = client.post(f"/api/v1/projects/{project}/conversations", json={}).json()["id"]
    base = f"/api/v1/conversations/{cid}"
    user = client.post(base + "/messages", json={"role": "user", "content": "Develop a moonlit scene"}).json()
    return cid, base, user


def test_pause_resume_cancel_and_restart_preserve_saved_request(tmp_path):
    provider = FakeAssistant()
    app = create_app(settings_for(tmp_path), planner_provider=provider)
    with TestClient(app) as client:
        project = create_project(client)
        cid, base, user = conversation(client, project)
        control = base + f"/messages/{user['id']}/task/"
        bridge = SimpleNamespace(session_factory=app.state.session_factory, project_id=project, message_id=user["id"])
        assert client.post(control + "pause").status_code == 200
        with pytest.raises(TaskStopped, match="paused"):
            check_task_control(bridge)
        assert client.post(base + "/reply", json={"message_id": user["id"]}).status_code == 409
        recover_interrupted_tasks(app.state.session_factory)
        assert client.get(base + "/messages").json()[-1]["metadata"]["task"]["state"] == "paused"
        assert client.post(control + "resume").status_code == 200
        check_task_control(bridge)
        assert client.post(base + "/reply", json={"message_id": user["id"]}).status_code == 200
        assert len(provider.calls) == 1
        assert client.post(base + "/reply", json={"message_id": user["id"]}).status_code == 200
        assert len(provider.calls) == 1
        _, other_base, other = conversation(client, project)
        other_control = other_base + f"/messages/{other['id']}/task/"
        assert client.post(other_control + "cancel").status_code == 200
        assert client.post(other_control + "resume").status_code == 409
        assert client.post(other_base + "/reply", json={"message_id": other["id"]}).status_code == 409
        assert client.post(base + f"/messages/{other['id']}/task/pause").status_code == 404
        with app.state.session_factory.begin() as session:
            saved = session.get(Message, other["id"])
            saved.metadata_json = {"task": {"state": "running"}}
        recover_interrupted_tasks(app.state.session_factory)
        assert client.get(other_base + "/messages").json()[-1]["metadata"]["task"]["state"] == "interrupted"


def test_project_memory_context_and_cross_project_story_updates(tmp_path):
    provider = FakeAssistant()
    app = create_app(settings_for(tmp_path), planner_provider=provider)
    with TestClient(app) as client:
        first, second = create_project(client, "A"), create_project(client, "B")
        character = client.post(f"/api/v1/projects/{second}/characters", json={"name": "Private character"}).json()
        scene = client.post(f"/api/v1/projects/{second}/scenes", json={"number": 1, "title": "Private scene"}).json()
        shot = client.post(f"/api/v1/scenes/{scene['id']}/shots", json={"number": 1}).json()
        memory = f"/api/v1/projects/{first}/assistant-context"
        assert client.put(memory, json={"character_id": character["id"]}).status_code == 422
        assert client.put(memory, json={"shot_id": shot["id"]}).status_code == 422
        assert client.put(memory, json={"notes": "Use muted blue lighting."}).status_code == 200
        _, base, user = conversation(client, first)
        assert client.post(base + "/reply", json={"message_id": user["id"]}).status_code == 200
        assert provider.calls[-1][0]["project_memory"]["notes"] == "Use muted blue lighting."
        assert client.get(f"/api/v1/projects/{second}/assistant-context").json()["notes"] == ""
        bridge = ComfyAssistantTools(app.state.settings, app.state.registry, app.state.session_factory, project_id=first)
        for kind, record in [("character", character), ("scene", scene), ("shot", shot)]:
            result = bridge.call({"operation": f"update_{kind}", "arguments": {"id": record["id"], "description": "leaked"}})
            assert "does not belong" in result["error"]
        assert client.delete(f"/api/v1/projects/{first}").status_code == 204


def test_workflow_owner_and_history_assets_are_scoped(tmp_path):
    provider = FakeAssistant()
    app = create_app(settings_for(tmp_path), planner_provider=provider)
    with TestClient(app) as client:
        first, second = create_project(client, "A"), create_project(client, "B")
        with app.state.session_factory.begin() as session:
            session.add(Asset(id="foreign", project_id=second, kind="image", path="foreign.png", content_hash="x", mime_type="image/png", provider="test"))
        _, base, user = conversation(client, first)
        client.post(base + "/messages", json={"role": "assistant", "content": "Old result", "metadata": {"reference_asset_ids": ["foreign"], "viewed_asset_ids": ["foreign"]}})
        latest = client.post(base + "/messages", json={"role": "user", "content": "Continue"}).json()
        assert client.post(base + "/reply", json={"message_id": latest["id"]}).status_code == 200
        assert all(not m["reference_asset_ids"] and not m["viewed_asset_ids"] for m in provider.calls[-1][0]["messages"])
        with app.state.session_factory() as session:
            contract = SimpleNamespace(id="assistant-owned", project_id=second, source_asset_ids=[])
            assert not workflow_available(session, first, contract)
            assert workflow_available(session, second, contract)
        assert client.put(f"/api/v1/projects/{first}/assistant-context", json={"reference_asset_ids": ["foreign"]}).status_code == 422


@pytest.mark.parametrize("arguments", ['{"workflow_id":', "[]", {"workflow_id": 22}, {"workflow_id": "example", "name": "Draft", "overrides": []}])
def test_invalid_tool_arguments_never_execute(tmp_path, monkeypatch, arguments):
    bridge = ComfyAssistantTools(settings_for(tmp_path), None, None)
    monkeypatch.setattr(bridge, "_call", lambda *_: pytest.fail("Invalid arguments executed"))
    result = bridge.call({"operation": "prepare_workflow", "arguments": arguments})
    assert result["error_code"] == "invalid_arguments"
    assert result["retryable"] is True


def test_fenced_json_and_numeric_limit_are_repaired_without_model_call(tmp_path, monkeypatch):
    bridge = ComfyAssistantTools(settings_for(tmp_path), None, None)
    monkeypatch.setattr(bridge, "_call", lambda operation, args, timeout: args)
    result = bridge.call({"operation": "list_assets", "arguments_json": '```json\n{"limit":"5"}\n```'})
    assert result["limit"] == 5


def test_pause_at_checkpoint_resumes_without_repeating_completed_tool(tmp_path):
    import json
    from darius_api.agent_harness import run_assistant_graph
    from test_agent_harness import final, request
    app = create_app(settings_for(tmp_path), planner_provider=FakeAssistant())
    with TestClient(app) as client:
        project = create_project(client)
        cid, base, user = conversation(client, project)
        bridge = ComfyAssistantTools(app.state.settings, app.state.registry, app.state.session_factory, project_id=project, message_id=user["id"])
        executed = []
        def tool(operation, args, timeout):
            executed.append(operation)
            assert client.post(base + f"/messages/{user['id']}/task/pause").status_code == 200
            return {"assets": []}
        bridge._call = tool
        calls = [{"output": [{"type": "function_call", "name": "comfyui", "call_id": "one",
            "arguments": json.dumps({"operation": "list_assets", "arguments": {}})}]}, final()]
        def model(*args, **kwargs):
            return calls.pop(0)
        with pytest.raises(TaskStopped):
            run_assistant_graph(app.state.settings, request(), user["id"], project, model, bridge.call)
        assert executed == ["list_assets"]
        assert len(calls) == 1
        client.post(base + f"/messages/{user['id']}/task/resume")
        result = run_assistant_graph(app.state.settings, request(), user["id"], project, model, bridge.call)
        assert executed == ["list_assets"]
        assert result["task"]["state"] == "replied"
