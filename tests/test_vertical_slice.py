from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from darius_api.config import Settings
from offline_fixtures import offline_definitions
from darius_api.database import Job, ProjectEvent
from darius_api.main import create_app
from darius_api.providers import ProviderResult
from darius_api.services import JobWorker


class FakeProvider:
    def __init__(self, output: Path):
        self.output = output

    def execute(self, contract, inputs, project_id, job_id) -> ProviderResult:  # noqa: ANN001
        assert contract.id == "minimax-h3-seamless-core"
        assert inputs["script"] == "A lantern flickers in an empty station."
        return ProviderResult(
            external_job_id="mock-prompt-123",
            outputs=(self.output,),
            metadata={"fixture": "fake-provider"},
            mocked=True,
        )


def make_settings(tmp_path: Path) -> Settings:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    return Settings(
        repository_root=repository,
        data_dir=data,
        database_url=f"sqlite:///{(data / 'test.db').as_posix()}",
        workflow_definitions_dir=offline_definitions(tmp_path),
        comfyui_base_url="http://127.0.0.1:1",
        ffprobe_path="missing-ffprobe-for-unit-test",
    )


def test_approved_request_is_persisted_ingested_and_exposes_provenance(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    source = tmp_path / "mock-output.mp4"
    source.write_bytes(b"clearly-mocked-video-output")
    app = create_app(settings)

    with TestClient(app) as client:
        project_response = client.post(
            "/api/v1/projects", json={"name": "Darius MVP Film"}
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

        workflows = client.get("/api/v1/workflows")
        assert workflows.status_code == 200
        assert {item["id"] for item in workflows.json()} >= {
            "krea2-turbo-text-to-image",
            "minimax-h3-seamless-core",
        }
        assert "maps_to" not in workflows.text

        request_payload = {
            "workflow_id": "minimax-h3-seamless-core",
            "request_text": "Generate a quiet station shot.",
            "inputs": {"script": "A lantern flickers in an empty station."},
        }
        unapproved = client.post(
            f"/api/v1/projects/{project_id}/requests", json=request_payload
        )
        assert unapproved.status_code == 409

        queued = client.post(
            f"/api/v1/projects/{project_id}/requests",
            json={**request_payload, "approved": True},
        )
        assert queued.status_code == 202
        job_id = queued.json()["id"]
        assert queued.json()["status"] == "queued"

        worker = JobWorker(
            app.state.session_factory,
            app.state.registry,
            settings,
            FakeProvider(source),
        )
        assert worker.run_once() == job_id

        completed = client.get(f"/api/v1/jobs/{job_id}")
        assert completed.status_code == 200
        job = completed.json()
        assert job["status"] == "completed"
        assert job["external_job_id"] == "mock-prompt-123"
        assert len(job["output_asset_ids"]) == 1

        asset_id = job["output_asset_ids"][0]
        provenance = client.get(f"/api/v1/assets/{asset_id}/provenance")
        assert provenance.status_code == 200
        body = provenance.json()
        asset = body["asset"]
        assert asset["kind"] == "video"
        assert asset["content_hash"] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert Path(asset["path"]).read_bytes() == source.read_bytes()
        assert Path(asset["path"]).resolve() != source.resolve()
        assert body["generation"]["prompt"] == "Generate a quiet station shot."
        assert body["generation"]["parameters"]["frames_per_shot"] == 192
        assert body["generation"]["provider_response_metadata"]["mocked"] is True

        with app.state.session_factory() as session:
            event_types = list(
                session.scalars(
                    select(ProjectEvent.event_type).where(ProjectEvent.project_id == project_id)
                )
            )
        assert event_types == [
            "project.created",
            "generation.queued",
            "asset.created",
            "generation.completed",
        ]

    restarted_app = create_app(settings)
    with TestClient(restarted_app) as restarted_client:
        persisted = restarted_client.get(f"/api/v1/jobs/{job_id}")
        assert persisted.status_code == 200
        assert persisted.json()["status"] == "completed"


def test_worker_records_provider_failures(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings)

    class BrokenProvider:
        def execute(self, contract, inputs, project_id, job_id):  # noqa: ANN001
            raise RuntimeError("intentional provider failure")

    with TestClient(app) as client:
        project_id = client.post("/api/v1/projects", json={"name": "Failure"}).json()["id"]
        queued = client.post(
            f"/api/v1/projects/{project_id}/requests",
            json={
                "workflow_id": "minimax-h3-seamless-core",
                "request_text": "Fail safely.",
                "inputs": {"script": "Failure fixture."},
                "approved": True,
            },
        ).json()
        worker = JobWorker(
            app.state.session_factory, app.state.registry, settings, BrokenProvider()
        )
        worker.run_once()
        failed = client.get(f"/api/v1/jobs/{queued['id']}").json()
        assert failed["status"] == "failed"
        assert failed["error_code"] == "RuntimeError"
        assert "intentional provider failure" in failed["error_detail"]
