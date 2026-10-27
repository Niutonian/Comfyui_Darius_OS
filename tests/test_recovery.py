from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from darius_api.config import Settings
from offline_fixtures import offline_definitions
from darius_api.database import Job
from darius_api.main import create_app
from darius_api.services import JobWorker, utcnow


class UnusedProvider:
    def execute(self, contract, inputs, project_id, job_id):  # noqa: ANN001
        raise AssertionError("provider should not run in recovery test")


def test_legacy_cloud_recovery_is_unchanged(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    settings = Settings(
        repository_root=repository,
        data_dir=data,
        database_url=f"sqlite:///{(data / 'test.db').as_posix()}",
        workflow_definitions_dir=offline_definitions(tmp_path),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        project_id = client.post("/api/v1/projects", json={"name": "Recovery"}).json()["id"]
        job_id = client.post(
            f"/api/v1/projects/{project_id}/requests",
            json={
                "workflow_id": "minimax-h3-seamless-core",
                "request_text": "Recover me.",
                "inputs": {"script": "Recovery fixture."},
                "approved": True,
            },
        ).json()["id"]
        with app.state.session_factory.begin() as session:
            job = session.get(Job, job_id)
            job.status = "running"
            job.provider = "bfl"
            job.heartbeat_at = utcnow() - timedelta(minutes=10)

        worker = JobWorker(
            app.state.session_factory, app.state.registry, settings, UnusedProvider()
        )
        assert worker.recover_abandoned(older_than=timedelta(minutes=5)) == 1
        recovered = client.get(f"/api/v1/jobs/{job_id}").json()
        assert recovered["status"] == "queued"
        assert recovered["status_message"] == "Recovered after worker restart"
