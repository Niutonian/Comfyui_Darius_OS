from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from dataclasses import replace
import shutil
import subprocess
import time

from fastapi.testclient import TestClient
import pytest

from darius_api.database import Job, utcnow
from darius_api.main import create_app
from darius_api.services import JobWorker, queue_timeline_render
from test_media_backend import create_project, settings_for


def accepted_cut(client):
    project = create_project(client)
    image = client.post("/api/v1/assets/upload", data={"project_id": project}, files={"file": ("frame.png", b"fixture", "image/png")}).json()
    timeline = client.post("/api/v1/timelines", json={"project_id": project, "name": "Cut"}).json()
    version = client.post(f"/api/v1/timelines/{timeline['id']}/versions", json={"state": "accepted", "tracks": [{"kind": "video", "clips": [{"id": "c", "source_asset_id": image["id"], "source_in": 0, "source_out": 1, "timeline_in": 0, "timeline_out": 1}]}]}).json()
    return project, timeline["id"], version["id"]


def test_approval_starts_only_the_new_cut_and_retry_starts_only_its_retry(tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr("darius_api.local_render.launch_local_job", lambda settings, jid: launched.append(jid))
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        project, timeline, version = accepted_cut(client)
        with app.state.session_factory.begin() as session:
            session.add(Job(id="unrelated", project_id=project, job_type="generation", provider="bfl", status="queued", input_payload={"approved": True}))
        path = f"/api/v1/timelines/{timeline}/render"
        assert client.post(path, json={"version_id": version, "approved": False}).status_code == 409
        assert not launched
        response = client.post(path, json={"version_id": version, "approved": True})
        assert response.status_code == 202
        job = response.json()
        assert launched == [job["id"]]
        assert client.get("/api/v1/jobs/unrelated").json()["status"] == "queued"
        with app.state.session_factory.begin() as session:
            session.get(Job, job["id"]).status = "failed"
        retried = client.post(f"/api/v1/jobs/{job['id']}/retry")
        assert retried.status_code == 201
        assert launched == [job["id"], retried.json()["id"]]
        assert retried.json()["retry_of_job_id"] == job["id"]


def test_two_devices_reserve_one_worker_and_stale_launch_can_be_retried(tmp_path, monkeypatch):
    launched = []
    def launch(settings, jid):
        launched.append(jid); time.sleep(.05)
    monkeypatch.setattr("darius_api.local_render.launch_local_job", launch)
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        _, timeline, version = accepted_cut(client)
        job = queue_timeline_render(app.state.session_factory, timeline, version, True)
        path = f"/api/v1/jobs/{job.id}/start-render"
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: client.post(path), range(2)))
        assert [r.status_code for r in responses] == [200, 200]
        assert launched == [job.id]
        assert client.post(path).status_code == 200
        assert launched == [job.id]
        with app.state.session_factory.begin() as session:
            row = session.get(Job, job.id)
            row.input_payload = {**row.input_payload, "timeline_worker_start": {"state": "started", "requested_at": (utcnow() - timedelta(seconds=31)).isoformat()}}
        assert client.post(path).status_code == 200
        assert launched == [job.id, job.id]


def test_launch_failure_remains_queued_and_can_be_started_again(tmp_path, monkeypatch):
    def fail(*args): raise PermissionError("fixture process failure")
    monkeypatch.setattr("darius_api.local_render.launch_local_job", fail)
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        _, timeline, version = accepted_cut(client)
        queued = client.post(f"/api/v1/timelines/{timeline}/render", json={"version_id": version, "approved": True}).json()
        assert queued["status"] == "queued"
        assert "Use Start render" in queued["status_message"]
        launched = []
        monkeypatch.setattr("darius_api.local_render.launch_local_job", lambda settings, jid: launched.append(jid))
        assert client.post(f"/api/v1/jobs/{queued['id']}/start-render").status_code == 200
        assert launched == [queued["id"]]


@pytest.mark.parametrize("change", ["generation", "unapproved", "cancelled", "foreign-version"])
def test_start_cannot_bypass_job_kind_approval_cancellation_or_project_scope(tmp_path, monkeypatch, change):
    launched = []
    monkeypatch.setattr("darius_api.local_render.launch_local_job", lambda settings, jid: launched.append(jid))
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        _, timeline, version = accepted_cut(client)
        job = queue_timeline_render(app.state.session_factory, timeline, version, True)
        _, other_timeline, other_version = accepted_cut(client)
        with app.state.session_factory.begin() as session:
            row = session.get(Job, job.id)
            if change == "generation": row.job_type = "generation"
            if change == "unapproved": row.input_payload = {**row.input_payload, "approved": False}
            if change == "cancelled": row.cancellation_requested = True
            if change == "foreign-version": row.input_payload = {**row.input_payload, "timeline_id": other_timeline, "timeline_version_id": other_version}
        assert client.post(f"/api/v1/jobs/{job.id}/start-render").status_code == 409
        assert not launched
        assert client.post("/api/v1/jobs/unknown/start-render").status_code == 404


def test_duplicate_workers_can_only_claim_the_target_once(tmp_path, monkeypatch):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        project, timeline, version = accepted_cut(client)
        one = queue_timeline_render(app.state.session_factory, timeline, version, True)
        two = queue_timeline_render(app.state.session_factory, timeline, version, True)
        worker = JobWorker(app.state.session_factory, app.state.registry, app.state.settings, None)
        assert worker.claim_next(two.id) == two.id
        assert worker.claim_next(two.id) is None
        assert client.get(f"/api/v1/jobs/{one.id}").json()["status"] == "queued"


def test_child_command_is_job_scoped_not_a_general_worker(tmp_path, monkeypatch):
    from darius_api.local_render import launch_local_job
    calls = []
    settings = settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _, timeline, version = accepted_cut(client)
        job = queue_timeline_render(app.state.session_factory, timeline, version, True)
        monkeypatch.setattr("darius_api.local_render.subprocess.Popen", lambda args, **kwargs: calls.append((args, kwargs)))
        launch_local_job(settings, job.id)
    assert calls[0][0][-2:] == ["--job-id", job.id]
    assert calls[0][1]["stdin"] is not None


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="native FFmpeg required")
def test_real_job_scoped_child_finishes_cut_and_leaves_other_queue_untouched(tmp_path, monkeypatch):
    settings = replace(settings_for(tmp_path), ffmpeg_path=shutil.which("ffmpeg"), ffprobe_path=shutil.which("ffprobe"))
    monkeypatch.setenv("PYTHONPATH", str(settings.repository_root / "apps" / "api"))
    monkeypatch.setenv("FFMPEG_PATH", settings.ffmpeg_path)
    monkeypatch.setenv("FFPROBE_PATH", settings.ffprobe_path)
    image = subprocess.run([settings.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=green:s=160x90", "-frames:v", "1", "-threads", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"], capture_output=True, check=True, timeout=15).stdout
    app = create_app(settings)
    children = []
    original = subprocess.Popen
    def spawn(args, **kwargs):
        child = original(args, **kwargs)
        if "darius_api.worker" in args: children.append(child)
        return child
    monkeypatch.setattr("darius_api.local_render.subprocess.Popen", spawn)
    try:
        with TestClient(app) as client:
            project = client.post("/api/v1/projects", json={"name": "Isolated child render", "default_resolution": "160x90", "default_fps": 20}).json()["id"]
            asset = client.post("/api/v1/assets/upload", data={"project_id": project}, files={"file": ("green.png", image, "image/png")}).json()
            timeline = client.post("/api/v1/timelines", json={"project_id": project, "name": "One-second CPU cut"}).json()["id"]
            version = client.post(f"/api/v1/timelines/{timeline}/versions", json={"state": "accepted", "tracks": [{"kind": "video", "clips": [{"id": "c", "source_asset_id": asset["id"], "source_in": 0, "source_out": 1, "timeline_in": 0, "timeline_out": 1}]}]}).json()["id"]
            with app.state.session_factory.begin() as session:
                session.add(Job(id="never-start-this-generation", project_id=project, job_type="generation", provider="bfl", status="queued", input_payload={"approved": True}))
            response = client.post(f"/api/v1/timelines/{timeline}/render", json={"version_id": version, "approved": True})
            assert response.status_code == 202
            jid = response.json()["id"]
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                job = client.get(f"/api/v1/jobs/{jid}").json()
                if job["status"] in {"completed", "failed"}: break
                time.sleep(.1)
            assert job["status"] == "completed", job.get("error_detail") or job["status_message"]
            assert job["attempt_count"] == 1
            assert len(children) == 1
            assert client.get("/api/v1/jobs/never-start-this-generation").json()["status"] == "queued"
            assert client.get(f"/api/v1/assets/{job['output_asset_ids'][0]}/content").status_code == 200
    finally:
        for child in children:
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired: child.terminate(); child.wait(timeout=5)
