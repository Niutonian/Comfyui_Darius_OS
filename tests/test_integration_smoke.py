from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from darius_api.config import Settings
from offline_fixtures import offline_definitions
from darius_api.main import create_app
from darius_api.providers import ProviderResult
from darius_api.services import JobWorker


class FakeSmokeProvider:
    """Explicitly fake provider: writes local fixture bytes and performs no network calls."""

    def __init__(self, output: Path) -> None:
        self.output = output

    def execute(self, contract, inputs, project_id, job_id) -> ProviderResult:  # noqa: ANN001
        assert contract.id == "minimax-h3-seamless-core"
        assert inputs["script"] == "Malik crosses the empty station."
        self.output.write_bytes(b"no-paid-call-fake-image")
        return ProviderResult(
            external_job_id="fake-smoke-job",
            outputs=(self.output,),
            metadata={"provider": "fake-smoke", "network_calls": 0},
            mocked=True,
        )


def smoke_settings(tmp_path: Path) -> Settings:
    root = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    return Settings(
        repository_root=root,
        data_dir=data,
        database_url=f"sqlite:///{(data / 'smoke.db').as_posix()}",
        workflow_definitions_dir=offline_definitions(tmp_path),
        comfyui_base_url="http://127.0.0.1:1",
        comfy_mcp_command="not-used-in-smoke",
        ffmpeg_path="not-used-in-smoke",
        ffprobe_path="not-used-in-smoke",
    )


def test_no_paid_call_structured_conversation_plan_and_timeline_smoke(tmp_path: Path) -> None:
    settings = smoke_settings(tmp_path)
    app = create_app(settings)
    fake_provider = FakeSmokeProvider(tmp_path / "fake-smoke.png")

    with TestClient(app) as client:
        preflight = client.options(
            "/api/v1/projects",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"

        project = client.post(
            "/api/v1/projects",
            json={
                "name": "No-paid-call Smoke Film",
                "description": "An offline integration proof.",
                "creative_brief": "A lone traveler enters an empty station.",
                "visual_style": "High-contrast monochrome",
                "default_aspect_ratio": "2.39:1",
                "default_resolution": "1920x804",
                "default_fps": 24,
            },
        ).json()
        project_id = project["id"]

        character = client.post(
            f"/api/v1/projects/{project_id}/characters",
            json={
                "name": "Malik",
                "description": "A cautious traveler.",
                "canonical_prompt": "Malik wearing a charcoal overcoat",
                "continuity_notes": "Keep the overcoat and silver watch consistent.",
                "metadata": {"story_role": "protagonist"},
            },
        )
        assert character.status_code == 201, character.text

        scene = client.post(
            f"/api/v1/projects/{project_id}/scenes",
            json={
                "number": 1,
                "title": "Empty Station",
                "screenplay_text": "Malik crosses the platform and listens.",
                "location": "Railway platform",
                "time_of_day": "Night",
                "mood": "Uneasy",
                "status": "planned",
            },
        ).json()

        conversation = client.post(
            f"/api/v1/projects/{project_id}/conversations",
            json={"title": "Opening sequence"},
        ).json()
        message = client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            json={
                "role": "user",
                "content": "Plan the opening shot without calling a paid provider.",
                "metadata": {"scene_id": scene["id"]},
            },
        )
        assert message.status_code == 201, message.text

        proposed = client.post(
            "/api/v1/workflows/minimax-h3-seamless-core/propose",
            json={
                "project_id": project_id,
                "request_text": "Create the opening visual.",
                "inputs": {"script": "Malik crosses the empty station."},
            },
        )
        assert proposed.status_code == 201, proposed.text
        plan = proposed.json()
        assert plan["state"] == "proposed"
        assert plan["conversation_id"] is None

        approved = client.post(f"/api/v1/action-plans/{plan['id']}/approve")
        assert approved.status_code == 200, approved.text
        job_id = approved.json()["job_id"]

        worker = JobWorker(
            app.state.session_factory,
            app.state.registry,
            settings,
            fake_provider,
        )
        assert worker.run_once() == job_id
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        assert job["status"] == "completed"
        assert len(job["output_asset_ids"]) == 1
        asset_id = job["output_asset_ids"][0]
        provenance = client.get(f"/api/v1/assets/{asset_id}/provenance").json()
        assert provenance["generation"]["provider_response_metadata"] == {
            "provider": "fake-smoke",
            "network_calls": 0,
            "mocked": True,
        }
        assert provenance["asset"]["metadata"]["mocked"] is True

        shot = client.post(
            f"/api/v1/scenes/{scene['id']}/shots",
            json={
                "number": 1,
                "description": "Malik enters frame.",
                "shot_type": "wide",
                "camera_motion": "locked",
                "duration_target": 5,
                "dialogue": "Hello?",
                "selected_asset_id": asset_id,
            },
        )
        assert shot.status_code == 201, shot.text

        timeline = client.post(
            "/api/v1/timelines",
            json={"project_id": project_id, "scene_id": scene["id"], "name": "Opening assembly"},
        ).json()
        proposal = client.post(f"/api/v1/timelines/{timeline['id']}/propose", json={})
        assert proposal.status_code == 201, proposal.text
        version = proposal.json()
        assert version["state"] == "proposed"
        assert version["tracks"][0]["clips"][0]["source_asset_id"] == asset_id
        assert version["tracks"][1]["clips"][0]["text"] == "Hello?"

        transitions = client.get(f"/api/v1/action-plans/{plan['id']}/transitions").json()
        assert [item["to_state"] for item in transitions] == [
            "proposed", "approved", "queued", "running", "review"
        ]


def test_committed_openapi_contract_matches_fastapi(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    committed = json.loads((root / "docs" / "openapi" / "darius-api.json").read_text(encoding="utf-8"))
    generated = create_app(smoke_settings(tmp_path)).openapi()
    assert committed == generated
    assert "/api/v1/projects/{project_id}/canvas-workspace" in generated["paths"]
    assert "/api/v1/bfl/connection" in generated["paths"]
    assert "/api/v1/projects/{project_id}/local-rendering" in generated["paths"]
    assert "/api/v1/conversations/{conversation_id}/reply" in generated["paths"]
    assert "/api/v1/assets/{asset_id}/content" in generated["paths"]
    assert "/api/v1/settings/llm" in generated["paths"]
    assert generated["paths"]["/api/v1/workflows"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["items"]["$ref"].endswith("/WorkflowView")
    assert generated["paths"]["/api/v1/assets/{asset_id}/provenance"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/AssetProvenanceView")
