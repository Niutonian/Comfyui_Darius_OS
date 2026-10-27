from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import json

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from darius_api.canvas_document import CanvasContent, CanvasRegion, Artboard, dimensions, resolve_regions, compile_regions
from darius_api.canvas_moss import compile_graph, template, digest, SOURCE_DIGEST, example
from darius_api.database import CanvasDocumentRecord, CanvasGenerationRecord, Job
from darius_api.main import create_app
from test_media_backend import settings_for, create_project


def region(key="a", **kwargs):
    return CanvasRegion(id=key, name=key, x=.1, y=.1, width=.4, height=.4, description="A red cube", **kwargs)


def test_nested_geometry_example_and_parent_scale():
    parent = CanvasRegion(id="parent", name="parent", kind="group", x=.25, y=.25, width=.5, height=.5)
    child = CanvasRegion(id="child", name="child", parentId="parent", x=.5, y=0, width=.5, height=.5)
    content = CanvasContent(regions=[child, parent])
    # Geometry is independent of the adapter's fixed 1 MP preset constraints.
    content.artboard = SimpleNamespace(width=1536, height=1024)
    assert resolve_regions(content)[1]["rect"] == (768, 256, 384, 256)


@pytest.mark.parametrize("bad", [dict(x=-.1), dict(width=0), dict(x=float("nan")), dict(height=float("inf")), dict(width=.95)])
def test_invalid_geometry_rejected(bad):
    value = region().model_dump(); value.update(bad)
    with pytest.raises(ValidationError): CanvasRegion.model_validate(value)


@pytest.mark.parametrize("parents", [("b", "a"), ("missing", None), ("a", None)])
def test_cycles_and_missing_parents_rejected(parents):
    with pytest.raises(ValidationError): CanvasContent(regions=[region("a", parentId=parents[0]), region("b", parentId=parents[1])])


def test_tree_order_group_visibility_and_character_index():
    parent = region("group", kind="group", order=0)
    text = region("text", parentId="group", kind="text", text='"你好"\nMOSS', order=0)
    char = region("character", parentId="group", kind="character", order=1)
    boxes, ids, labels = compile_regions(CanvasContent(regions=[char, text, parent]))
    assert ids == ["text", "character"] and labels == "2"
    assert boxes[0]["metadata"]["text"] == '"你好"\nMOSS'
    parent.visible = False
    assert compile_regions(CanvasContent(globalPrompt="Empty scene", regions=[parent, text, char])) == ([], [], "")


def test_inherited_lock_is_editor_state_not_pixel_protection():
    values = resolve_regions(CanvasContent(regions=[region("p", locked=True), region("c", parentId="p")]))
    assert all(value["locked"] for value in values)
    assert len(compile_regions(CanvasContent(regions=[v["region"] for v in values]))[0]) == 2


def test_adapter_preserves_master_and_only_changes_allowlisted_values(tmp_path):
    settings = settings_for(tmp_path)
    original = template(settings)
    graph, provenance = compile_graph(settings, CanvasContent(globalPrompt="A red cube", regions=[region()]), 42)
    assert digest(original) == SOURCE_DIGEST and template(settings) == original
    changed = {(node_id, key) for node_id, node in graph.items() for key, value in node["inputs"].items()
               if value != original[node_id]["inputs"].get(key)}
    assert changed <= {("19", "aspect_ratio"), ("25", "editor_state"), ("25", "last_incoming"),
        ("27", "prompt"), ("27", "character_boxes"), ("18:16", "switch"), ("18:7", "seed"), ("9", "filename_prefix")}
    assert graph["18:16"]["inputs"]["switch"] is False
    assert graph["25"]["inputs"]["last_incoming"] == {"__value__": []}
    assert graph["18:7"]["inputs"]["steps"] == 25 and graph["18:7"]["inputs"]["cfg"] == 2.5
    assert provenance["regionIndexMap"] == ["a"] and not provenance["capabilities"]["pixelProtection"]


def test_import_uses_current_state_not_previous_and_preserves_text(tmp_path):
    value = example(settings_for(tmp_path))
    first = value["content"]["regions"][0]
    assert first["y"] == 736 / 1024 and first["text"] == "MOSS"
    assert len(value["content"]["regions"]) == 6 and value["warnings"]


@pytest.fixture
def canvas_client(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    definitions = tmp_path / "definitions"; definitions.mkdir()
    settings = replace(settings, workflow_definitions_dir=definitions)
    monkeypatch.setattr("darius_api.canvas_api.readiness", lambda *a: {"ready": True, "issues": []})
    monkeypatch.setattr("darius_api.providers.ComfyMcpProvider.validate_api_graph", lambda *a, **k: {"valid": True, "errors": []})
    launches = []
    monkeypatch.setattr("darius_api.local_render.launch_local_job", lambda s, key: launches.append(key))
    app = create_app(settings)
    with TestClient(app) as client:
        project = create_project(client)
        yield client, app, project, launches


def create_canvas(client, project):
    response = client.post(f"/api/v1/projects/{project}/canvases", json=CanvasContent(globalPrompt="A red cube").model_dump())
    assert response.status_code == 201, response.text
    return response.json()


def test_save_reopen_cas_and_immutable_revisions(canvas_client):
    client, app, project, _ = canvas_client
    doc = create_canvas(client, project)
    url = f"/api/v1/projects/{project}/canvases/{doc['id']}"
    content = doc["content"]; content["name"] = "New name"
    saved = client.post(url + "/save", json={"revision": 1, "content": content})
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    assert client.post(url + "/save", json={"revision": 1, "content": content}).status_code == 409
    assert client.get(url).json()["content"]["name"] == "New name"
    assert client.get(url + "/revisions/1").json()["content"]["name"] == "Untitled canvas"
    assert client.get(f"/api/v1/projects/other/canvases/{doc['id']}").status_code == 404


def test_generation_is_explicit_and_idempotent_with_one_seed(canvas_client):
    client, app, project, launches = canvas_client
    doc = create_canvas(client, project)
    url = f"/api/v1/projects/{project}/canvases/{doc['id']}/generate"
    request = {"revision": 1, "idempotencyKey": "test-request-one"}
    assert client.post(url, json=request).status_code == 422
    request["approved"] = True
    first = client.post(url, json=request)
    assert first.status_code == 200, first.text
    second = client.post(url, json=request)
    assert first.json() == second.json() and len(launches) == 1
    assert 0 <= first.json()["seed"] < 2**32
    with app.state.session_factory() as session:
        assert len(list(session.scalars(select(CanvasGenerationRecord)))) == 1


def test_old_completion_never_overwrites_new_document_or_user_version_choice(canvas_client):
    from darius_api.canvas_api import completed
    client, app, project, _ = canvas_client
    doc = create_canvas(client, project)
    base = f"/api/v1/projects/{project}/canvases/{doc['id']}"
    receipt = client.post(base + "/generate", json={"revision": 1, "idempotencyKey": "test-request-two", "seed": 42, "approved": True}).json()
    content = deepcopy(doc["content"]); content["globalPrompt"] = "A blue sphere"
    assert client.post(base + "/save", json={"revision": 1, "content": content}).status_code == 200
    with app.state.session_factory.begin() as session:
        job = session.get(Job, receipt["jobId"]); job.status = "completed"
        completed(session, job, {"canvas_compiled_layout": "verified"})
    current = client.get(base).json()
    assert current["revision"] == 2 and current["activeGenerationId"] is None
    assert current["content"]["globalPrompt"] == "A blue sphere"
    assert current["generations"][0]["revision"] == 1


@pytest.mark.parametrize("failure", ["missing-model", "invalid-graph", "offline"])
def test_preflight_failure_retains_document_without_queueing(canvas_client, monkeypatch, failure):
    client, app, project, launches = canvas_client
    doc = create_canvas(client, project)
    if failure == "missing-model":
        monkeypatch.setattr("darius_api.canvas_api.readiness", lambda *a: {"ready": False, "issues": ["Missing model: moss"]})
    elif failure == "invalid-graph":
        monkeypatch.setattr("darius_api.providers.ComfyMcpProvider.validate_api_graph", lambda *a, **k: {"valid": False, "errors": ["invalid node"]})
    else:
        def offline(*args): raise TimeoutError("ComfyUI did not respond")
        monkeypatch.setattr("darius_api.canvas_api.readiness", offline)
    url = f"/api/v1/projects/{project}/canvases/{doc['id']}"
    failed = client.post(url + "/generate", json={"revision": 1, "idempotencyKey": "failed-attempt", "approved": True})
    assert failed.status_code == 422 and "retained" in failed.json()["detail"]
    assert client.get(url).json()["content"] == doc["content"] and not launches
    with app.state.session_factory() as session:
        assert session.scalar(select(CanvasGenerationRecord)) is None
        assert session.scalar(select(Job)) is None


def test_canvas_jobs_are_internal_not_available_to_chat_as_recipes(canvas_client):
    from darius_api.services import enqueue_request, RequestError
    client, app, project, _ = canvas_client
    doc = create_canvas(client, project)
    receipt = client.post(f"/api/v1/projects/{project}/canvases/{doc['id']}/generate", json={"revision": 1, "idempotencyKey": "internal-recipe", "approved": True}).json()
    with app.state.session_factory() as session:
        workflow_id = session.get(Job, receipt["jobId"]).input_payload["workflow_id"]
    assert workflow_id not in {w.id for w in app.state.registry.enabled()}
    assert workflow_id in {w.id for w in app.state.registry.enabled(include_internal=True)}
    with pytest.raises(RequestError, match="Canvas"):
        enqueue_request(app.state.session_factory, app.state.registry, project, workflow_id, "Another subject", {}, True)


def test_worker_start_failure_keeps_one_recoverable_job(canvas_client, monkeypatch):
    client, app, project, _ = canvas_client
    doc = create_canvas(client, project)
    def unavailable(*args): raise OSError("Worker launch failed")
    monkeypatch.setattr("darius_api.local_render.launch_local_job", unavailable)
    base = f"/api/v1/projects/{project}/canvases/{doc['id']}"
    payload = {"revision": 1, "idempotencyKey": "worker-unavailable", "approved": True}
    first = client.post(base + "/generate", json=payload).json()
    assert "launchError" in first and first["status"] == "queued"
    second = client.post(base + "/generate", json=payload).json()
    assert first["jobId"] == second["jobId"] and first["seed"] == second["seed"]
    launches = []
    monkeypatch.setattr("darius_api.local_render.launch_local_job", lambda s, key: launches.append(key))
    assert client.post(base + f"/generations/{first['id']}/start").status_code == 200
    assert launches == [first["jobId"]]


def test_failed_job_retains_revision_and_does_not_become_selected(canvas_client):
    client, app, project, _ = canvas_client
    doc = create_canvas(client, project)
    base = f"/api/v1/projects/{project}/canvases/{doc['id']}"
    run = client.post(base + "/generate", json={"revision": 1, "idempotencyKey": "interrupted-job", "approved": True}).json()
    with app.state.session_factory.begin() as session:
        job = session.get(Job, run["jobId"]); job.status = "failed"; job.error_detail = "Execution interrupted"
    reopened = client.get(base).json()
    assert reopened["content"] == doc["content"] and reopened["activeGenerationId"] is None
    assert reopened["generations"][0]["assetIds"] == []
    assert client.post(base + "/select-result", json={"generationId": run["id"]}).status_code == 409


def test_cross_document_generation_cannot_be_selected(canvas_client):
    client, _, project, _ = canvas_client
    first, second = create_canvas(client, project), create_canvas(client, project)
    base = f"/api/v1/projects/{project}/canvases"
    run = client.post(base + f"/{first['id']}/generate", json={"revision": 1, "idempotencyKey": "same-project-other-doc", "approved": True}).json()
    assert client.post(base + f"/{second['id']}/select-result", json={"generationId": run["id"]}).status_code == 404
    assert client.get(base + f"/{second['id']}/generations/{run['id']}/provenance").status_code == 404


def test_provider_collects_only_declared_save_node_and_records_runtime(tmp_path, monkeypatch):
    from darius_api.providers import ComfyMcpProvider
    from darius_api.workflows import WorkflowContract
    from darius_api.atomic_files import atomic_json
    settings = settings_for(tmp_path)
    graph, _ = compile_graph(settings, CanvasContent(globalPrompt="A red cube"), 42)
    source = tmp_path / "canvas.json"; atomic_json(source, graph)
    contract = WorkflowContract(id="canvas-test", name="Canvas", version="moss-bboxes-v1", capability="text-to-image",
        execution_provider="local-comfyui", workflow_reference=str(source), required_inputs=[], output={"kind": "image"},
        runtime_mapping={"api_format": True, "filename_prefix_slot": "9.filename_prefix"}, output_node_ids=["9"], internal_only=True)
    provider = ComfyMcpProvider(settings)
    monkeypatch.setattr("darius_api.providers.validate_graph", lambda graph, **kw: graph)
    monkeypatch.setattr("darius_api.canvas_moss.runtime_environment", lambda s: {"system": {"comfyui_version": "0.42.4"}})
    monkeypatch.setattr(provider, "validate_api_graph", lambda *a, **k: {"valid": True, "errors": []})
    monkeypatch.setattr(provider, "_submit_verified_local_graph", lambda *a, **k: {"data": {"prompt_id": "prompt-123"}})
    monkeypatch.setattr(provider, "_history", lambda *a: {"status": {"completed": True}, "outputs": {
        "9": {"images": [{"filename": "final.png"}]}, "fake-preview": {"images": [{"filename": "not-final.png"}]},
        "26": {"text": ['{"items":[]}']}}})
    collected = []
    monkeypatch.setattr(provider, "_collect", lambda h: collected.append(h) or [])
    result = provider._execute_with_gpu(contract, {}, "project-a", "job-a", manual_approval=True)
    assert set(collected[0]["outputs"]) == {"9"}
    assert result.external_job_id == "prompt-123" and result.metadata["canvas_compiled_layout"] == '{"items":[]}'
    assert result.metadata["canvas_environment"]["system"]["comfyui_version"] == "0.42.4"
    assert len(result.metadata["canvas_executed_graph_digest"]) == 64
