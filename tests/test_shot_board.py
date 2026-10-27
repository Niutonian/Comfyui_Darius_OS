from fastapi.testclient import TestClient
from darius_api.main import create_app
from darius_api.database import Asset, Job
from test_media_backend import settings_for, create_project


def test_board_links_are_durable_project_scoped_and_render_progress_is_separate(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        project = create_project(client)
        foreign = create_project(client, "Other")
        scene = client.post(f"/api/v1/projects/{project}/scenes", json={"number": 1, "title": "Station"}).json()["id"]
        shot = client.post(f"/api/v1/scenes/{scene}/shots", json={"number": 1, "description": "Arrival"}).json()["id"]
        with app.state.session_factory.begin() as session:
            for aid, pid, kind in [("ref", project, "image"), ("take", project, "video"), ("foreign", foreign, "image")]:
                session.add(Asset(id=aid, project_id=pid, kind=kind, role="source", path=str(tmp_path / aid), content_hash=aid, mime_type="image/png", provider="fixture"))
            session.add(Job(id="render", project_id=project, provider="fixture", status="completed", input_payload={"production_context": {"shot_id": shot, "scene_id": scene}}, output_asset_ids=["take", "foreign"]))
        path = f"/api/v1/projects/{project}/shot-board"
        patch = path + "/" + shot
        assert client.get(path).json()[0]["takes"][0]["id"] == "take"
        assert client.get(path).json()[0]["shot"]["status"] == "planned"
        assert client.patch(patch, json={"reference_asset_ids": ["foreign"]}).status_code == 422
        assert client.patch(patch, json={"reference_asset_ids": ["take"]}).status_code == 422
        assert client.patch(patch, json={"status": "complete"}).status_code == 422
        assert client.patch(f"/api/v1/projects/{foreign}/shot-board/{shot}", json={"status": "ready"}).status_code == 404
        assert client.patch(patch, json={"reference_asset_ids": ["ref"], "selected_asset_id": "take", "status": "selected"}).status_code == 200
        row = client.get(path).json()[0]
        assert row["references"][0]["id"] == "ref"
        assert row["shot"]["selected_asset_id"] == "take"
        assert row["jobs"][0]["status"] == "completed"
        with app.state.session_factory() as session:
            assert session.get(Asset, "take").shot_id is None  # Links do not move shared media.
        assert client.patch(patch, json={"status": "complete"}).status_code == 200
        assert client.patch(patch, json={"selected_asset_id": None, "status": "generated"}).status_code == 200
        assert client.get(f"/api/v1/projects/{foreign}/shot-board").json() == []
        # Project deletion must clean up board links before its shots.
        assert client.delete(f"/api/v1/projects/{project}").status_code == 204


def test_message_snapshots_active_shot_instead_of_trusting_client_metadata(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        project = create_project(client)
        scene = client.post(f"/api/v1/projects/{project}/scenes", json={"number": 1, "title": "Arrival"}).json()["id"]
        shot = client.post(f"/api/v1/scenes/{scene}/shots", json={"number": 1}).json()["id"]
        assert client.put(f"/api/v1/projects/{project}/assistant-context", json={"scene_id": scene, "shot_id": shot}).status_code == 200
        cid = client.post(f"/api/v1/projects/{project}/conversations", json={}).json()["id"]
        message = client.post(f"/api/v1/conversations/{cid}/messages", json={"role": "user", "content": "Generate the shot", "metadata": {"production_context": {"shot_id": "foreign"}}}).json()
        assert message["metadata"]["production_context"] == {"scene_id": scene, "shot_id": shot}
