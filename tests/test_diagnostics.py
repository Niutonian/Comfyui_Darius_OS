import json
from dataclasses import replace

from fastapi.testclient import TestClient

from darius_api.database import Message
from darius_api.diagnostics import access_key, reset_access_key, local_json, record, redact, tail
from darius_api.main import create_app
from test_media_backend import create_project, settings_for
import pytest


def test_access_code_persists_and_sensitive_values_are_redacted(tmp_path):
    settings = settings_for(tmp_path)
    key = access_key(settings)
    assert len(key) >= 32 and access_key(settings) == key
    text = redact('Authorization: Bearer abc-secret api_key=private password="private2" {"secret": "private3"} sk-abcdefghijklmnop')
    for secret in ("abc-secret", "private", "private2", "private3", "sk-abcdefghijklmnop"):
        assert secret not in text
    record(settings, "backend", "error", "test", password="private3")
    assert "private3" not in tail(settings.data_dir / "diagnostics" / "backend.jsonl")


def test_no_remote_url_or_redirect_input_is_accepted():
    for base in ("https://remote.example", "http://remote.example", "http://user:pass@127.0.0.1"):
        with pytest.raises(ValueError, match="loopback"):
            local_json(base, "/queue")


@pytest.mark.parametrize('encoding', ['utf-8-sig', 'utf-16'])
def test_access_code_accepts_windows_text_encodings(tmp_path, encoding):
    settings = settings_for(tmp_path)
    key = access_key(settings)
    path = settings.data_dir / 'diagnostics/access-code.txt'
    path.write_text(key + '\n', encoding=encoding)
    assert access_key(settings) == key


def test_local_console_code_reset_takes_effect_without_api_restart(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    app = create_app(settings)
    monkeypatch.setattr('darius_api.diagnostics.service_snapshot', lambda *args: ([], ''))
    with TestClient(app) as client:
        old = access_key(settings)
        reset_access_key(settings)
        current = access_key(settings)
        assert current != old
        assert client.get('/api/v1/diagnostics', headers={'X-Darius-Diagnostics-Key': old}).status_code == 401
        assert client.get('/api/v1/diagnostics', headers={'X-Darius-Diagnostics-Key': current}).status_code == 200


def test_console_requires_key_scopes_failures_and_never_exports_credentials(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    app = create_app(settings)
    monkeypatch.setattr("darius_api.diagnostics.service_snapshot", lambda *args: ([{"name": "ComfyUI", "state": "offline", "detail": "Connection refused"}], "terminal output"))
    with TestClient(app) as client:
        assert client.get("/api/v1/diagnostics?logs=true").status_code == 401
        assert client.get("/api/v1/diagnostics", headers={"X-Darius-Diagnostics-Key": "wrong"}).status_code == 401
        projects = [create_project(client, name) for name in ("own", "other")]
        for project in projects:
            conversation = client.post(f"/api/v1/projects/{project}/conversations", json={"title": "test"}).json()["id"]
            message = client.post(f"/api/v1/conversations/{conversation}/messages", json={"role": "user", "content": "private prompt"}).json()["id"]
            with app.state.session_factory.begin() as session:
                session.get(Message, message).metadata_json = {"task": {"state": "failed", "error": f"{project} timed out"}}
        key = app.state.diagnostic_key
        response = client.get(f"/api/v1/diagnostics?project_id={projects[0]}&logs=true", headers={"X-Darius-Diagnostics-Key": key})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert projects[0] in json.dumps(response.json()["failures"])
        assert projects[1] not in json.dumps(response.json()["failures"])
        assert "private prompt" not in response.text and key not in response.text
        assert response.json()["logs"]["comfyui"] == "terminal output"
        assert client.get("/api/v1/diagnostics?project_id=unknown", headers={"X-Darius-Diagnostics-Key": key}).status_code == 404
        assert key not in tail(settings.data_dir / "diagnostics" / "backend.jsonl")


def test_optional_comfy_terminal_endpoint_can_fail_without_hiding_status(tmp_path, monkeypatch):
    from darius_api.diagnostics import service_snapshot
    def mock(base, endpoint):
        if endpoint == "/queue":
            return {"queue_running": [1], "queue_pending": []}
        raise OSError("No logs endpoint")
    monkeypatch.setattr("darius_api.diagnostics.local_json", mock)
    checks, logs = service_snapshot(settings_for(tmp_path), "openai")
    assert checks[1]["state"] == "ready"
    assert "unavailable" in logs
