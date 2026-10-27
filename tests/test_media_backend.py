from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from darius_api.config import Settings
from darius_api.database import Asset, Base, ProjectEvent
from darius_api.main import create_app
from darius_api.providers import ProviderError
from darius_api.services import JobWorker


def settings_for(tmp_path: Path) -> Settings:
    root = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    return Settings(
        repository_root=root,
        data_dir=data,
        database_url=f"sqlite:///{(data / 'media-backend.db').as_posix()}",
        workflow_definitions_dir=root / "workflows" / "definitions",
        comfyui_base_url="http://127.0.0.1:1",
        comfy_mcp_command="unused-comfy",
        ffmpeg_path="test-ffmpeg",
        ffprobe_path="test-ffprobe",
    )


def create_project(client: TestClient, name: str = "Media Backend") -> str:
    response = client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_initial_alembic_migration_matches_metadata_and_round_trips(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration.db"
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")

    command.upgrade(config, "head")
    from darius_api.database import make_engine

    engine = make_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    for table_name, table in Base.metadata.tables.items():
        migrated_columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert migrated_columns == set(table.columns.keys())
    command.check(config)
    engine.dispose()

    command.downgrade(config, "base")
    engine = make_engine(f"sqlite:///{database.as_posix()}")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_derivatives_and_webcam_capture_persist_assets_and_events(tmp_path: Path, monkeypatch) -> None:
    settings = settings_for(tmp_path)

    def fake_run(args, timeout):  # noqa: ANN001
        assert isinstance(args, list)
        destination = Path(args[-1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"mocked-ffmpeg-derivative")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("darius_api.media_processing._run", fake_run)
    app = create_app(settings)
    with TestClient(app) as client:
        project_id = create_project(client)
        upload = client.post(
            "/api/v1/assets/upload",
            data={"project_id": project_id},
            files={"file": ("still.png", b"immutable-source", "image/png")},
        )
        source = upload.json()
        result = client.post(f"/api/v1/assets/{source['id']}/derivatives")
        assert result.status_code == 200, result.text
        derivatives = result.json()["derivatives"]
        assert {item["metadata"]["derivative_type"] for item in derivatives} == {"thumbnail", "proxy"}
        assert all(item["role"] == "derivative" for item in derivatives)
        assert all(item["parent_asset_ids"] == [source["id"]] for item in derivatives)
        assert Path(source["path"]).read_bytes() == b"immutable-source"

        capture = client.post(
            "/api/v1/assets/webcam-capture",
            data={"project_id": project_id},
            files={"file": ("capture.webm", b"immutable-webcam", "video/webm")},
        )
        assert capture.status_code == 201, capture.text
        body = capture.json()
        assert body["asset"]["metadata"]["capture_source"] == "webcam"
        assert len(body["derivatives"]) == 2
        assert Path(body["asset"]["path"]).read_bytes() == b"immutable-webcam"

        with app.state.session_factory() as session:
            events = list(session.scalars(select(ProjectEvent.event_type)))
        assert events.count("asset.derivative_created") == 4
        assert events.count("asset.derivatives_processed") == 2


def test_derivatives_fail_gracefully_when_ffmpeg_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    settings = settings_for(tmp_path)

    def unavailable(args, timeout):  # noqa: ANN001
        raise FileNotFoundError("ffmpeg missing")

    monkeypatch.setattr("darius_api.media_processing._run", unavailable)
    app = create_app(settings)
    with TestClient(app) as client:
        project_id = create_project(client)
        source = client.post(
            "/api/v1/assets/upload", data={"project_id": project_id},
            files={"file": ("still.jpg", b"source", "image/jpeg")},
        ).json()
        response = client.post(f"/api/v1/assets/{source['id']}/derivatives")
        assert response.status_code == 200
        assert response.json()["derivatives"] == []
        assert len(response.json()["warnings"]) == 2


def test_media_analysis_uses_argument_lists_and_persists_facts(tmp_path: Path, monkeypatch) -> None:
    settings = settings_for(tmp_path)
    calls: list[tuple[list[str], dict]] = []

    def fake_subprocess_run(args, **kwargs):  # noqa: ANN001
        calls.append((args, kwargs))
        if args[0] == "test-ffprobe":
            return subprocess.CompletedProcess(args, 0, json.dumps({"streams": [{"codec_type": "video"}]}), "")
        if "-af" in args:
            stderr = "silence_start: 1.0\nsilence_end: 2.5 | silence_duration: 1.5\n"
        else:
            stderr = (
                "black_start:3 black_end:4 black_duration:1\n"
                "freeze_start: 5\nfreeze_end: 7 | freeze_duration: 2\n"
                "[Parsed_showinfo] n:1 pts:100 pts_time:8.25\n"
            )
        return subprocess.CompletedProcess(args, 0, "", stderr)

    monkeypatch.setattr("darius_api.media_processing.subprocess.run", fake_subprocess_run)
    app = create_app(settings)
    with TestClient(app) as client:
        project_id = create_project(client)
        asset = client.post(
            "/api/v1/assets/upload", data={"project_id": project_id},
            files={"file": ("clip.mp4", b"mock-video", "video/mp4")},
        ).json()
        response = client.post(
            f"/api/v1/assets/{asset['id']}/analyze",
            json={"scene_threshold": 0.7, "silence_duration": 0.25},
        )
        assert response.status_code == 200, response.text
        facts = response.json()["facts"]
        assert facts["silence"] == [{"start": 1.0, "end": 2.5, "duration": 1.5}]
        assert facts["black"][0]["start"] == 3.0
        assert facts["freeze"][0]["duration"] == 2.0
        assert facts["scenes"] == [{"time": 8.25, "score": None}]
        persisted = client.get(f"/api/v1/assets/{asset['id']}").json()
        assert persisted["metadata"]["media_analysis"]["scenes"][0]["time"] == 8.25

    assert calls
    assert all(isinstance(args, list) for args, _ in calls)
    assert all(kwargs["shell"] is False for _, kwargs in calls)
    assert all("capture_output" in kwargs and kwargs["capture_output"] is True for _, kwargs in calls)


def test_timeline_validation_otio_and_approved_worker_render(tmp_path: Path, monkeypatch) -> None:
    # Endpoint now requests its job-scoped child; this test drives an injected worker itself.
    monkeypatch.setattr("darius_api.local_render.launch_local_job", lambda *args: None)
    settings = settings_for(tmp_path)
    app = create_app(settings)

    class UnusedGenerationProvider:
        def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("generation provider must not run for timeline render")

    class FakeTimelineRenderer:
        def __init__(self) -> None:
            self.calls = 0

        def render(self, version, assets, project, output, render_settings):  # noqa: ANN001
            self.calls += 1
            assert version.state == "accepted"
            assert assets
            assert render_settings is settings
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"mocked-timeline-render")
            return output

    renderer = FakeTimelineRenderer()
    with TestClient(app) as client:
        project_id = create_project(client)
        source = client.post(
            "/api/v1/assets/upload", data={"project_id": project_id},
            files={"file": ("frame.png", b"frame", "image/png")},
        ).json()
        timeline = client.post(
            "/api/v1/timelines", json={"project_id": project_id, "name": "Validated cut"},
        ).json()
        valid_tracks = [{
            "kind": "video", "clips": [{
                "id": "clip-1", "source_asset_id": source["id"],
                "source_in": 0, "source_out": 2, "timeline_in": 0, "timeline_out": 2,
            }],
        }]
        version_response = client.post(
            f"/api/v1/timelines/{timeline['id']}/versions",
            json={"tracks": valid_tracks, "state": "accepted", "edit_summary": "Approved test cut."},
        )
        assert version_response.status_code == 201, version_response.text
        version = version_response.json()
        assert version["edit_summary"] == "Approved test cut."
        exposed_paths = client.get("/openapi.json").json()["paths"]
        for path in (
            "/api/v1/assets/webcam-capture",
            "/api/v1/assets/{asset_id}/derivatives",
            "/api/v1/assets/{asset_id}/analyze",
            "/api/v1/conversations/{conversation_id}/plan",
            "/api/v1/timelines/{timeline_id}/versions/{version_id}/otio",
            "/api/v1/timelines/{timeline_id}/render",
        ):
            assert path in exposed_paths

        invalid = client.post(
            f"/api/v1/timelines/{timeline['id']}/versions",
            json={"tracks": [{"kind": "video", "clips": [
                valid_tracks[0]["clips"][0],
                {**valid_tracks[0]["clips"][0], "id": "clip-2", "timeline_in": 1, "timeline_out": 3},
            ]}]},
        )
        assert invalid.status_code == 409
        assert "overlap" in invalid.json()["detail"]

        otio = client.get(f"/api/v1/timelines/{timeline['id']}/versions/{version['id']}/otio")
        assert otio.status_code == 200
        assert otio.json()["OTIO_SCHEMA"] == "Timeline.1"
        clip = otio.json()["tracks"]["children"][0]["children"][0]
        assert clip["OTIO_SCHEMA"] == "Clip.2"
        assert clip["media_reference"]["metadata"]["darius_asset_id"] == source["id"]

        denied = client.post(
            f"/api/v1/timelines/{timeline['id']}/render",
            json={"version_id": version["id"], "approved": False},
        )
        assert denied.status_code == 409
        assert renderer.calls == 0
        queued = client.post(
            f"/api/v1/timelines/{timeline['id']}/render",
            json={"version_id": version["id"], "approved": True},
        )
        assert queued.status_code == 202, queued.text
        assert renderer.calls == 0
        job_id = queued.json()["id"]

        worker = JobWorker(
            app.state.session_factory, app.state.registry, settings,
            UnusedGenerationProvider(), timeline_renderer=renderer,
        )
        assert worker.run_once() == job_id
        assert renderer.calls == 1
        completed = client.get(f"/api/v1/jobs/{job_id}").json()
        assert completed["status"] == "completed"
        output = client.get(f"/api/v1/assets/{completed['output_asset_ids'][0]}").json()
        assert output["role"] == "render"
        assert output["provider"] == "ffmpeg"
        assert output["parent_asset_ids"] == [source["id"]]
        assert Path(output["path"]).read_bytes() == b"mocked-timeline-render"


def test_conversation_planning_is_explicit_and_dependency_injected(tmp_path):
    class Planner:
        def ready(self): return True
        def plan(self,*args): pytest.fail('Retired /plan endpoint must not invoke the model')
    with TestClient(create_app(settings_for(tmp_path),planner_provider=Planner())) as client:
        project=create_project(client)
        conversation=client.post(f'/api/v1/projects/{project}/conversations',json={}).json()
        base=f"/api/v1/conversations/{conversation['id']}"
        user=client.post(base+'/messages',json={'role':'user','content':'Do not plan automatically.'}).json()
        response=client.post(base+'/plan',json={'request_text':'Propose the next safe action.'})
        assert response.status_code==410
        assert 'boards' in response.text
        assert [m['id'] for m in client.get(base+'/messages').json()]==[user['id']]
        assert client.get(f'/api/v1/jobs?project_id={project}').json()==[]



def test_asset_content_streams_managed_media_and_rejects_unsafe_paths(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    app = create_app(settings)
    payload = b"immutable-image-fixture"

    with TestClient(app) as client:
        project_id = create_project(client, "Content delivery")
        asset = client.post(
            "/api/v1/assets/upload",
            data={"project_id": project_id},
            files={"file": ("result.png", payload, "image/png")},
        ).json()

        content = client.get(f"/api/v1/assets/{asset['id']}/content")
        assert content.status_code == 200
        assert content.content == payload
        assert content.headers["content-type"] == "image/png"
        assert "immutable" in content.headers["cache-control"]
        assert content.headers["x-content-type-options"] == "nosniff"

        outside = tmp_path / "outside.png"
        outside.write_bytes(b"must-not-be-served")
        with app.state.session_factory.begin() as session:
            session.get(Asset, asset["id"]).path = str(outside)
        rejected = client.get(f"/api/v1/assets/{asset['id']}/content")
        assert rejected.status_code == 404
        assert rejected.json()["detail"] == "asset content does not exist"

        with app.state.session_factory.begin() as session:
            session.get(Asset, asset["id"]).path = str(settings.data_dir / "missing.png")
        missing = client.get(f"/api/v1/assets/{asset['id']}/content")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "asset content does not exist"
