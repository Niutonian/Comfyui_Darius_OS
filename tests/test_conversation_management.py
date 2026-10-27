from fastapi.testclient import TestClient
from darius_api.main import create_app
from darius_api.database import ActionPlan, WorkflowDefinitionRecord
from sqlalchemy import select
from test_media_backend import settings_for, create_project
from test_assistant import FakeAssistant
from concurrent.futures import ThreadPoolExecutor
import threading


def test_rename_delete_are_project_scoped_and_keep_action_plans(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        project = create_project(client)
        other = create_project(client, "Other")
        chat = client.post(f"/api/v1/projects/{project}/conversations", json={"title": "New chat"}).json()
        cid = chat["id"]
        path = f"/api/v1/projects/{project}/conversations/{cid}"
        foreign = f"/api/v1/projects/{other}/conversations/{cid}"
        client.post(f"/api/v1/conversations/{cid}/messages", json={"role": "user", "content": "Saved message"})
        with app.state.session_factory.begin() as session:
            workflow = session.scalar(select(WorkflowDefinitionRecord))
            session.add(ActionPlan(id="retained-plan", project_id=project, conversation_id=cid, workflow_definition_id=workflow.id, request_text="Keep this plan", provider="fixture", inputs={}, expected_output={}))
        assert client.patch(foreign, json={"title": "Wrong"}).status_code == 404
        assert client.delete(foreign).status_code == 404
        assert client.patch(path, json={"title": "   "}).status_code == 422
        assert client.patch(path, json={"title": "x" * 301}).status_code == 422
        assert client.patch(path, json={"title": "  Renamed chat  "}).json()["title"] == "Renamed chat"
        assert client.get(f"/api/v1/projects/{project}/conversations").json()[0]["title"] == "Renamed chat"
        assert client.delete(path).json() == {"deleted": cid}
        assert client.get(f"/api/v1/conversations/{cid}/messages").status_code == 404
        assert client.get(f"/api/v1/projects/{project}/conversations").json() == []
        with app.state.session_factory() as session:
            assert session.get(ActionPlan, "retained-plan").conversation_id is None
        assert client.delete(path).status_code == 404


def test_cannot_delete_a_chat_while_reply_is_running(tmp_path):
    entered, finish = threading.Event(), threading.Event()
    class WaitingAssistant(FakeAssistant):
        def plan(self, context, text):
            entered.set()
            assert finish.wait(5)
            return super().plan(context, text)
    with TestClient(create_app(settings_for(tmp_path), planner_provider=WaitingAssistant())) as client:
        project = create_project(client)
        cid = client.post(f"/api/v1/projects/{project}/conversations", json={}).json()["id"]
        mid = client.post(f"/api/v1/conversations/{cid}/messages", json={"role": "user", "content": "Hello"}).json()["id"]
        with ThreadPoolExecutor() as pool:
            reply = pool.submit(client.post, f"/api/v1/conversations/{cid}/reply", json={"message_id": mid})
            try:
                assert entered.wait(5)
                assert client.delete(f"/api/v1/projects/{project}/conversations/{cid}").status_code == 409
            finally:
                finish.set()
            assert reply.result().status_code == 200
