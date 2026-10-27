import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from darius_api.bfl_catalog import contracts, resolve_media, reference_ids
from darius_api.database import Asset, Job
from darius_api.main import create_app
from darius_api.providers import BflProvider, ProviderError, LlamaCppPlannerProvider, OpenCodePlannerProvider
from darius_api.services import JobWorker
from test_mvp_expansion import make_settings
from test_media_backend import create_project
from test_opencode_provider import media_body


def contract(identifier):
    return next(item for item in contracts() if item.id == identifier)


@pytest.mark.parametrize("identifier,inputs", [
    ("bfl-flux-3-image", {"prompt": "Garvin in the vat bay", "resolution": "4k", "grounding": False}),
    ("bfl-flux-3-image-edit", {"prompt": "Change the lighting", "images": ["asset:image-a", "asset:image-b"]}),
    ("bfl-flux-3-text-to-video", {"prompt": "Garvin turns", "duration": 20, "resolution": "uhd", "generate_audio": True}),
    ("bfl-flux-3-image-to-video", {"prompt": "Move closer", "keyframes": [[0, "asset:a"], [8, "asset:b"]], "duration": 8}),
    ("bfl-flux-3-video-continuation", {"prompt": "Continue walking", "start_video": "video-asset", "duration": 15}),
    ("bfl-flux-3-draft-enhance", {"draft_cache": "draft-asset", "resolution": "uhd"}),
    ("bfl-flux-3-video-edit", {"prompt": "Remove the ship", "video": "video-asset"}),
    ("bfl-flux-3-video-upscale", {"input_video": "video-asset", "creativity": 0, "upscale_factor": 3}),
])
def test_all_cloud_modes_expose_and_validate_documented_fields(identifier, inputs):
    normalized = contract(identifier).validate_inputs(inputs)
    assert normalized.items() >= inputs.items()


@pytest.mark.parametrize("inputs", [
    {"duration": 4}, {"duration": 9.5}, {"resolution": "8k"}, {"seed": 42}, {"safety_tolerance": 5}, {"mode": "i2v"},
])
def test_video_invalid_or_unsupported_parameters_fail_before_submit(inputs):
    with pytest.raises(ValueError):
        contract("bfl-flux-3-text-to-video").validate_inputs({"prompt": "Garvin turns", **inputs})


def test_keyframe_count_and_timing_constraints():
    workflow = contract("bfl-flux-3-image-to-video")
    for frames in ([], ["a"] * 11, [[8, "a"], [0, "b"]], [[0, "a"], [9, "b"]]):
        with pytest.raises(ValueError):
            workflow.validate_inputs({"prompt": "Garvin turns", "keyframes": frames, "duration": 8})
    with pytest.raises(ValueError, match="explicit duration"):
        workflow.validate_inputs({"prompt": "Garvin turns", "keyframes": ["a", "b", "c"]})


def test_provider_honors_polling_url_and_keeps_video_kind(tmp_path, monkeypatch):
    provider = BflProvider(replace(make_settings(tmp_path), bfl_api_key="private-fixture-key"))
    calls = []
    def request(method, path, payload=None):
        calls.append((method, path, payload))
        return {"id": "remote", "polling_url": "https://api.bfl.ai/v1/get_result?id=remote", "cost": 60} if method == "POST" else {"status": "Ready", "result": {"sample": "https://delivery.example/output.mp4"}}
    monkeypatch.setattr(provider, "_request", request)
    remote = provider.submit({"endpoint": "flux-3-video", "parameters": {"mode": "t2v", "prompt": "Garvin turns"}}, approved=True)
    assert remote.metadata["cost_credits"] == 60
    assert provider.collect("remote")[0].kind == "video"
    assert calls[-1][1] == "https://api.bfl.ai/v1/get_result?id=remote"
    with pytest.raises(ProviderError, match="official HTTPS"):
        provider._url("https://attacker.example/poll")


def test_resume_never_posts_twice_and_saves_draft_cache(tmp_path, monkeypatch):
    provider = BflProvider(replace(make_settings(tmp_path), bfl_api_key="fixture"))
    saved = []
    posts = []
    def request(method, path, payload=None):
        if method == "POST":
            posts.append(payload)
            return {"id": "remote", "polling_url": "https://api.bfl.ai/v1/get_result?id=remote"}
        return {"status": "Ready", "result": {"sample": "https://delivery.example/clip.mp4", "draft_cache": "https://delivery.example/cache.bin"}}
    monkeypatch.setattr(provider, "_request", request)
    def download(url, path):
        path.write_bytes(b"fixture-output")
        return path
    monkeypatch.setattr(provider, "_download", download)
    workflow = contract("bfl-flux-3-text-to-video")
    inputs = workflow.validate_inputs({"prompt": "Garvin turns", "draft": True, "duration": 8})
    result = provider.execute(workflow, inputs, "p", "job-a", on_submission=lambda value: saved.append(dict(value)))
    resumed = provider.execute(workflow, inputs, "p", "job-b", submission=saved[-1])
    assert len(posts) == 1
    assert result.outputs[0].suffix == ".mp4"
    assert Path(resumed.metadata["bfl_draft_cache_path"]).is_file()
    assert saved[0] == {"submission_started": True}


def test_lost_submission_response_is_not_resubmitted(tmp_path, monkeypatch):
    provider = BflProvider(replace(make_settings(tmp_path), bfl_api_key="fixture"))
    monkeypatch.setattr(provider, "_request", lambda *args: pytest.fail("Resubmitted a paid request"))
    workflow = contract("bfl-flux-3-image")
    with pytest.raises(ProviderError, match="NOT made"):
        provider.execute(workflow, workflow.validate_inputs({"prompt": "Garvin"}), "p", "job", submission={"submission_started": True})


def test_cloud_api_uses_approval_scoped_assets_and_real_worker_adapter(tmp_path, monkeypatch):
    settings = replace(make_settings(tmp_path), bfl_api_key="fixture")
    app = create_app(settings)
    requests = []
    def request(self, method, path, payload=None):
        requests.append((method, path, payload))
        return {"id": "bfl-job", "polling_url": "https://api.bfl.ai/v1/get_result?id=bfl-job"} if method == "POST" else {"status": "Ready", "result": {"sample": "https://delivery.example/image.png"}}
    monkeypatch.setattr(BflProvider, "_request", request)
    def download(self, url, destination):
        destination.write_bytes(b"test-image")
        return destination
    monkeypatch.setattr(BflProvider, "_download", download)
    with TestClient(app) as client:
        project = create_project(client)
        workflows = client.get("/api/v1/workflows").json()
        assert len([item for item in workflows if item["execution_provider"] == "bfl"]) == 8
        options = client.get("/api/v1/workflows/bfl-flux-3-text-to-video/input-options").json()
        assert "uhd" in options["resolution"] and 20 in options["duration"]
        body = {"project_id": project, "request_text": "Garvin in the vat bay", "inputs": {"prompt": "Garvin in the vat bay"}}
        proposed = client.post("/api/v1/workflows/bfl-flux-3-image/propose", json=body)
        assert proposed.status_code == 201, proposed.text
        assert requests == []
        plan_id = proposed.json()["id"]
        job_id = client.post(f"/api/v1/action-plans/{plan_id}/approve").json()["job_id"]
        assert requests == []  # Approval queues; only the worker submits.
        worker = JobWorker(app.state.session_factory, app.state.registry, settings, object())
        worker.run_once(job_id)
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        assert job["status"] == "completed", job
        assert job["external_job_id"] == "bfl-job"
        assert len([item for item in requests if item[0] == "POST"]) == 1
        assert requests[0][2]["prompt"] == body["request_text"]
        output = client.get(f"/api/v1/assets?project_id={project}").json()[0]
        assert output["kind"] == "image" and output["provider"] == "bfl"
        other = create_project(client, "Other silo")
        leaked = client.post("/api/v1/workflows/bfl-flux-3-image-edit/propose", json={"project_id": other, "request_text": "Edit", "inputs": {"prompt": "Edit lighting", "images": [f"asset:{output['id']}"]}})
        assert leaked.status_code == 409, leaked.text
        with app.state.session_factory() as session:
            values = resolve_media(session, project, {"images": [f"asset:{output['id']}"]}, settings, encode=True)
            assert values["images"][0].startswith("data:image/png;base64,")
        assert reference_ids({"keyframes": [[0, f"asset:{output['id']}"]]}) == [output["id"]]


@pytest.mark.parametrize("provider_type", [LlamaCppPlannerProvider, OpenCodePlannerProvider])
def test_selected_cloud_workflow_does_not_need_comfy_discovery(tmp_path, monkeypatch, provider_type):
    provider = provider_type(make_settings(tmp_path))
    monkeypatch.setattr(provider, "_resolve_visual_prompt", lambda *args: ("Garvin turns inside the vat bay.", ""))
    response = provider._responses(media_body("Generate a video of Garvin", {"preferred_workflow_id": "bfl-flux-3-text-to-video", "preferred_workflow": {"execution_provider": "bfl", "output": {"kind": "video"}}}))
    answer = json.loads(response["output"][0]["content"][0]["text"])
    assert answer["workflow_id"] == "bfl-flux-3-text-to-video"
    assert "no paid request" in answer["reply"]
