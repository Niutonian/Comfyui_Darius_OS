from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from darius_api.config import Settings, _load_root_env
from offline_fixtures import offline_definitions
from darius_api.main import create_app
from darius_api.providers import BflProvider, OpenAIPlannerProvider, ProviderError


def make_settings(tmp_path: Path, *, max_upload_bytes: int = 1024 * 1024) -> Settings:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    return Settings(
        repository_root=repository,
        data_dir=data,
        database_url=f"sqlite:///{(data / 'expanded.db').as_posix()}",
        workflow_definitions_dir=offline_definitions(tmp_path),
        comfyui_base_url="http://127.0.0.1:1",
        comfy_mcp_command="missing-comfy-for-test",
        ffmpeg_path="missing-ffmpeg-for-test",
        ffprobe_path="missing-ffprobe-for-test",
        max_upload_bytes=max_upload_bytes,
    )


def test_project_entities_upload_conversation_timeline_and_sse(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        project = client.post(
            "/api/v1/projects",
            json={
                "name": "Expanded Film",
                "creative_brief": "A compact proof",
                "visual_style": "Noir",
                "default_fps": 25,
            },
        )
        assert project.status_code == 201
        project_id = project.json()["id"]
        assert client.get("/api/v1/projects").json()[0]["creative_brief"] == "A compact proof"

        scene = client.post(
            f"/api/v1/projects/{project_id}/scenes",
            json={"number": 1, "title": "Station", "screenplay_text": "A light flickers."},
        )
        assert scene.status_code == 201
        scene_id = scene.json()["id"]

        original = b"immutable-fake-png"
        upload = client.post(
            "/api/v1/assets/upload",
            data={"project_id": project_id, "role": "reference", "scene_id": scene_id, "approval_state": "approved"},
            files={"file": ("reference.png", original, "image/png")},
        )
        assert upload.status_code == 201, upload.text
        asset = upload.json()
        asset_id = asset["id"]
        stored = Path(asset["path"])
        assert stored.read_bytes() == original
        assert stored.name != "reference.png"
        assert asset["content_hash"] == hashlib.sha256(original).hexdigest()
        assert settings.data_dir.resolve() in stored.resolve().parents

        character = client.post(
            f"/api/v1/projects/{project_id}/characters",
            json={
                "name": "Malik",
                "canonical_prompt": "Malik in a dark coat",
                "approved_reference_asset_ids": [asset_id],
                "metadata": {"age_range": "30s"},
            },
        )
        assert character.status_code == 201, character.text
        assert character.json()["approved_reference_asset_ids"] == [asset_id]
        assert character.json()["metadata"] == {"age_range": "30s"}

        shot = client.post(
            f"/api/v1/scenes/{scene_id}/shots",
            json={
                "number": 1,
                "description": "Malik enters",
                "duration_target": 4.5,
                "dialogue": "Is anybody here?",
                "selected_asset_id": asset_id,
            },
        )
        assert client.get("/api/v1/assets", params={"project_id": project_id, "q": "reference.png"}).json()[0]["id"] == asset_id

        assert shot.status_code == 201, shot.text
        shot_id = shot.json()["id"]

        search = client.get("/api/v1/assets", params={"project_id": project_id, "kind": "image", "role": "reference"})
        assert search.status_code == 200
        assert [item["id"] for item in search.json()] == [asset_id]
        provenance = client.get(f"/api/v1/assets/{asset_id}/provenance").json()
        assert provenance["generation"] is None
        assert provenance["import"]["original_filename"] == "reference.png"

        conversation = client.post(
            f"/api/v1/projects/{project_id}/conversations", json={"title": "Opening scene"}
        ).json()
        message = client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            json={"role": "user", "content": "Build this cut.", "metadata": {"scene_id": scene_id}},
        )
        assert message.status_code == 201
        assert client.get(f"/api/v1/conversations/{conversation['id']}/messages").json()[0]["content"] == "Build this cut."

        timeline = client.post(
            "/api/v1/timelines",
            json={"project_id": project_id, "scene_id": scene_id, "name": "Assembly"},
        ).json()
        proposal = client.post(f"/api/v1/timelines/{timeline['id']}/propose", json={})
        assert proposal.status_code == 201, proposal.text
        version = proposal.json()
        assert version["version_number"] == 1
        assert version["state"] == "proposed"
        clip = version["tracks"][0]["clips"][0]
        assert clip["source_asset_id"] == asset_id
        assert clip["shot_id"] == shot_id
        assert clip["timeline_in"] == 0.0
        assert clip["timeline_out"] == 4.5
        # The same structured inputs always yield the same edit decisions.
        second = client.post(f"/api/v1/timelines/{timeline['id']}/propose", json={}).json()
        assert second["tracks"] == version["tracks"]
        assert second["version_number"] == 2

        detail = client.get(f"/api/v1/projects/{project_id}").json()
        assert (detail["character_count"], detail["scene_count"], detail["asset_count"]) == (1, 1, 1)
        events = client.get(f"/api/v1/projects/{project_id}/events").json()
        assert {event["event_type"] for event in events} >= {
            "project.created", "asset.created", "character.created", "scene.created",
            "shot.created", "conversation.message_created", "timeline.version_created",
        }
        stream = client.get("/api/v1/events/stream", params={"project_id": project_id, "once": "true"})
        assert stream.status_code == 200
        assert "event: project_event" in stream.text
        assert "event: jobs" in stream.text


def test_action_plan_approval_cancel_retry_and_transition_history(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        project_id = client.post("/api/v1/projects", json={"name": "Plan Film"}).json()["id"]
        proposal = client.post(
            "/api/v1/workflows/minimax-h3-seamless-core/propose",
            json={
                "project_id": project_id,
                "request_text": "Generate the opening.",
                "inputs": {"script": "A safe local proposal."},
            },
        )
        assert proposal.status_code == 201, proposal.text
        plan_id = proposal.json()["id"]
        assert proposal.json()["state"] == "proposed"

        approved = client.post(f"/api/v1/action-plans/{plan_id}/approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["state"] == "queued"
        job_id = approved.json()["job_id"]
        assert client.get("/api/v1/jobs", params={"project_id": project_id, "status": "queued"}).json()[0]["id"] == job_id

        cancelled = client.post(f"/api/v1/action-plans/{plan_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["state"] == "cancelled"
        assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "cancelled"
        transitions = client.get(f"/api/v1/action-plans/{plan_id}/transitions").json()
        assert [item["to_state"] for item in transitions] == ["proposed", "approved", "queued", "cancelled"]

        retry = client.post(f"/api/v1/jobs/{job_id}/retry")
        assert retry.status_code == 201, retry.text
        assert retry.json()["status"] == "queued"
        assert retry.json()["retry_of_job_id"] == job_id
        assert client.post(f"/api/v1/jobs/{retry.json()['id']}/cancel").json()["status"] == "cancelled"


def test_configuration_loading_readiness_upload_limit_and_provider_gates(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / ".env").write_text("SAFE_NEW_VALUE=loaded\nEXISTING_VALUE=from-file\n# ignored\n", encoding="utf-8")
    monkeypatch.delenv("SAFE_NEW_VALUE", raising=False)
    monkeypatch.setenv("EXISTING_VALUE", "from-process")
    _load_root_env(root)
    assert __import__("os").environ["SAFE_NEW_VALUE"] == "loaded"
    assert __import__("os").environ["EXISTING_VALUE"] == "from-process"

    settings = make_settings(tmp_path, max_upload_bytes=4)
    assert OpenAIPlannerProvider(settings).ready() is False
    with pytest.raises(ProviderError, match="explicit approval"):
        BflProvider(settings).submit({"endpoint": "generate", "parameters": {}}, approved=False)

    app = create_app(settings)
    with TestClient(app) as client:
        project_id = client.post("/api/v1/projects", json={"name": "Limits"}).json()["id"]
        too_large = client.post(
            "/api/v1/assets/upload",
            data={"project_id": project_id},
            files={"file": ("large.png", b"12345", "image/png")},
        )
        assert too_large.status_code == 413
        assert not list((settings.data_dir / "projects" / project_id / "sources").glob("*"))
        health = client.get("/api/v1/health").json()
        assert health["components"]["openai"] == {"ready": False, "configured": False, "optional": True}
        assert health["components"]["bfl"] == {"ready": False, "configured": False, "optional": True}
        assert health["components"]["tts"]["ready"] is False
        assert health["components"]["transcription"]["ready"] is False
