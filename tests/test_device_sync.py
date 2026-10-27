"""Project sync uses durable events and canonical reads, never extra model requests."""
import json

from fastapi.testclient import TestClient

from darius_api.main import create_app
from test_media_backend import create_project, settings_for


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and '"event_type"' in line]


def test_live_subscription_starts_at_current_watermark_but_resume_replays_missed_events(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as desktop:
        phone = TestClient(app)
        project = create_project(desktop)
        chat = desktop.post(f"/api/v1/projects/{project}/conversations", json={"title": "Shared chat"}).json()
        stream = f"/api/v1/events/stream?project_id={project}&once=true"
        previous = events(desktop.get(stream))[-1]["id"]
        initial = desktop.get(stream + "&live=true")
        assert "event: ready" in initial.text
        assert not events(initial)  # No replay storm for an old, busy project.
        posted = phone.post(f"/api/v1/conversations/{chat['id']}/messages", json={"role": "user", "content": "Written on my phone"}).json()
        received = events(desktop.get(stream + "&live=true", headers={"Last-Event-ID": previous}))
        assert [event["entity_id"] for event in received] == [posted["id"]]
        assert desktop.get(f"/api/v1/conversations/{chat['id']}/messages").json()[0]["content"] == "Written on my phone"


def test_renames_and_deletes_are_broadcast_without_other_project_history(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as desktop:
        phone = TestClient(desktop.app)
        project = create_project(desktop)
        other = create_project(desktop, "Private other project")
        chat = desktop.post(f"/api/v1/projects/{project}/conversations", json={"title": "Shared chat"}).json()
        path = f"/api/v1/projects/{project}/conversations/{chat['id']}"
        phone.patch(path, json={"title": "Renamed from phone"}).raise_for_status()
        phone.post(f"/api/v1/projects/{other}/conversations", json={"title": "Not shared"}).raise_for_status()
        stream = events(desktop.get(f"/api/v1/events/stream?project_id={project}&once=true"))
        assert all(event["project_id"] == project for event in stream)
        assert any(event["event_type"] == "conversation.renamed" and event["entity_id"] == chat["id"] for event in stream)
        assert desktop.get(f"/api/v1/projects/{project}/conversations").json()[0]["title"] == "Renamed from phone"
        phone.delete(path).raise_for_status()
        assert events(desktop.get(f"/api/v1/events/stream?project_id={project}&once=true"))[-1]["event_type"] == "conversation.deleted"
        assert desktop.get(f"/api/v1/conversations/{chat['id']}/messages").status_code == 404
