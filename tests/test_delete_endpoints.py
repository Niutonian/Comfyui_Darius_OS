from fastapi.testclient import TestClient

from darius_api.main import create_app
from test_media_backend import create_project, settings_for


def test_delete_project_is_project_scoped(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        project_id = create_project(client, "Delete me")
        assert client.delete(f"/api/v1/projects/{project_id}").status_code == 204
        assert all(item["id"] != project_id for item in client.get("/api/v1/projects").json())


def test_delete_missing_asset_returns_not_found(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        assert client.delete("/api/v1/assets/missing").status_code == 404


def test_update_project_name(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        project_id = create_project(client, "Before")
        response = client.patch(f"/api/v1/projects/{project_id}", json={"name": "After"})
        assert response.status_code == 200
        assert response.json()["name"] == "After"
