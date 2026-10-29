from copy import deepcopy
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from test_canvas import canvas_client, create_canvas
from darius_api.database import (MossBoardRecord as Board, CanvasGenerationRecord as Generation,
    CanvasDocumentRecord as Document, CanvasRevisionRecord as Revision, Job, Asset)
from darius_api.canvas_api import completed
from darius_api.gpu_handoff import gpu_lease
from darius_api.services import JobWorker


def root(project): return f"/api/v1/projects/{project}/canvas-workspace"


def add(client, project, name="Board", **values):
    result = client.post(root(project) + "/boards", json={"name": name, "x": 0, "y": 0, **values})
    assert result.status_code == 201, result.text
    value = result.json()
    return next(b for b in value["workspace"]["boards"] if b["id"] == value["boardId"])


def generate(client, project, board, key="moss-request-one", **values):
    # Populate a supported semantic description before requesting a real task.
    path = f"/api/v1/projects/{project}/canvases/{board['documentId']}"
    doc = client.get(path).json()
    if not doc["content"]["globalPrompt"]:
        content = {**doc["content"], "globalPrompt": "A red cube on a cream background"}
        doc = client.post(path + "/save", json={"revision": doc["revision"], "content": content}).json()
    result = client.post(path + "/generate", json={"revision": doc["revision"], "idempotencyKey": key,
        "approved": True, "boardId": board["id"], "boardRevision": board["revision"], **values})
    assert result.status_code == 200, result.text
    return result.json()


def fake_result(app, project, receipt):
    asset_id = receipt["id"]
    with app.state.session_factory.begin() as session:
        job = session.get(Job, receipt["jobId"])
        asset = Asset(id=asset_id, project_id=project, kind="image", role="generation", path=f"/mock/{asset_id}.png",
            content_hash="a" * 64, mime_type="image/png", provider="local-comfyui", workflow_run_id=job.id)
        session.add(asset); session.flush()
        job.status = "completed"; job.output_asset_ids = [asset.id]
        completed(session, job, {"canvas_compiled_layout": "verified"})
    return asset_id


def test_lazy_migration_preserves_document_and_is_idempotent(canvas_client):
    client, _, project, _ = canvas_client
    old = create_canvas(client, project)
    first = client.get(root(project)).json()
    second = client.get(root(project)).json()
    assert first == second and len(first["boards"]) == 1
    assert first["boards"][0]["documentId"] == old["id"]
    assert client.get(f"/api/v1/projects/{project}/canvases/{old['id']}").json()["content"] == old["content"]


def test_layout_geometry_and_cas_are_independent_of_documents(canvas_client):
    client, _, project, _ = canvas_client
    a, b = add(client, project, "A"), add(client, project, "B")
    workspace = client.get(root(project)).json()
    placements = deepcopy(workspace["placements"]); placements[0].update(x=-1200, y=840, displayWidth=500)
    result = client.post(root(project) + "/layout", json={"revision": workspace["revision"], "placements": placements})
    assert result.status_code == 200
    assert client.post(root(project) + "/layout", json={"revision": workspace["revision"], "placements": placements}).status_code == 409
    for board in [a, b]:
        doc = client.get(f"/api/v1/projects/{project}/canvases/{board['documentId']}").json()
        assert doc["revision"] == 1 and doc["content"]["artboard"]["width"] == 1024


def test_duplicate_makes_new_document_without_jobs_or_history(canvas_client):
    client, _, project, _ = canvas_client
    a = add(client, project, "A")
    generate(client, project, a)
    b = add(client, project, "A copy", duplicateBoardId=a["id"])
    assert a["id"] != b["id"] and a["documentId"] != b["documentId"]
    assert b["jobs"] == [] and b["latest"] is None and b["documentRevision"] == 1
    doc = client.get(f"/api/v1/projects/{project}/canvases/{b['documentId']}").json()
    assert "red cube" in doc["content"]["globalPrompt"]


def test_edits_during_preflight_cannot_mutate_a_frozen_request(canvas_client, monkeypatch):
    client, app, project, _ = canvas_client
    a, b = add(client, project, "A"), add(client, project, "B")
    path = f"/api/v1/projects/{project}/canvases/{a['documentId']}"
    def during_preflight(*args):
        doc = client.get(path).json()
        client.post(path + "/save", json={"revision": doc["revision"], "content": {**doc["content"], "globalPrompt": "A newer blue sphere"}})
        settings = {**b["settings"], "seed": 99}
        assert client.post(root(project) + f"/boards/{b['id']}", json={"revision": b["revision"], "settings": settings}).status_code == 200
        return {"ready": True, "issues": []}
    monkeypatch.setattr("darius_api.canvas_api.readiness", during_preflight)
    receipt = generate(client, project, a, seed=42)
    with app.state.session_factory() as session:
        generation = session.get(Generation, receipt["id"])
        assert generation.revision == 2 and generation.provenance_json["board"]["boardId"] == a["id"]
        assert session.get(Document, a["documentId"]).revision == 3
        source = session.get(Revision, (a["documentId"], 2)).content_json
        assert "red cube" in source["globalPrompt"]
        assert session.get(Job, receipt["jobId"]).input_payload["canvas_revision"] == 2
    fake_result(app, project, receipt)
    assert client.get(path).json()["activeGenerationId"] is None


def test_reference_pins_completed_version_and_never_conditions_moss(canvas_client):
    client, app, project, _ = canvas_client
    a, b = add(client, project, "A"), add(client, project, "B")
    first = generate(client, project, a); asset_id = fake_result(app, project, first)
    reference = {"id": "pinned-a", "sourceBoardId": a["id"], "sourceGenerationId": first["id"], "assetId": asset_id, "assetVersionId": "a" * 64, "role": "visual-note"}
    value = {"revision": b["revision"], "settings": {**b["settings"], "references": [reference]}}
    updated = client.post(root(project) + f"/boards/{b['id']}", json=value)
    assert updated.status_code == 200, updated.text
    b = updated.json()
    second = generate(client, project, a, "new-source-version"); fake_result(app, project, second)
    current = next(x for x in client.get(root(project)).json()["boards"] if x["id"] == b["id"])
    assert current["settings"]["references"] == [reference] and current["jobs"] == []
    run_b = generate(client, project, b, "target-with-visual-note")
    assert run_b["provenance"]["board"]["references"] == [reference]
    with app.state.session_factory() as session:
        from pathlib import Path
        import json
        job = session.get(Job, run_b["jobId"])
        graph = json.loads(Path(app.state.registry.get(job.input_payload["workflow_id"]).workflow_reference).read_text())
        assert not any(node["class_type"] in {"LoadImage", "LoadImageMask"} for node in graph.values())
        assert reference["assetId"] not in str(graph)


@pytest.mark.parametrize("wrong", ["hash", "generation", "project", "role"])
def test_invalid_reference_rejected(canvas_client, wrong):
    client, app, project, _ = canvas_client
    a, b = add(client, project, "A"), add(client, project, "B")
    run = generate(client, project, a); asset_id = fake_result(app, project, run)
    ref = {"id": "pinned", "sourceBoardId": a["id"], "sourceGenerationId": run["id"], "assetId": asset_id, "assetVersionId": "a"*64, "role": "visual-note"}
    if wrong == "hash": ref["assetVersionId"] = "b"*64
    if wrong == "generation": ref["sourceGenerationId"] = "missing"
    if wrong == "project": ref["sourceBoardId"] = "foreign-board"
    if wrong == "role": ref["role"] = "image-conditioning"
    response = client.post(root(project) + f"/boards/{b['id']}", json={"revision": 1, "settings": {**b["settings"], "references": [ref]}})
    assert response.status_code in {404, 422}


def test_queued_cancel_and_archive_keep_other_work_and_documents(canvas_client):
    client, app, project, _ = canvas_client
    a, b = add(client, project, "A"), add(client, project, "B")
    run_a, run_b = generate(client, project, a, "job-for-a"), generate(client, project, b, "job-for-b")
    assert client.post(root(project) + f"/boards/{a['id']}/cancel/{run_b['jobId']}").status_code == 404
    assert client.post(root(project) + f"/boards/{a['id']}/cancel/{run_a['jobId']}").status_code == 200
    with app.state.session_factory.begin() as session:
        job = session.get(Job, run_b["jobId"]); assert job.status == "queued"; job.status = "running"
    assert client.post(root(project) + f"/boards/{b['id']}/cancel/{run_b['jobId']}").status_code == 409
    assert client.post(root(project) + f"/boards/{b['id']}", json={"revision": 1, "settings": b["settings"], "archived": True}).status_code == 200
    assert client.get(f"/api/v1/projects/{project}/canvases/{b['documentId']}").status_code == 200
    with app.state.session_factory() as session:
        assert session.get(Job, run_b["jobId"]).status == "running"


def test_chat_command_uses_captured_board_and_same_idempotent_path(canvas_client):
    from test_assistant import FakeAssistant
    client,app,project,_=canvas_client
    provider=FakeAssistant();app.state.planner_provider=provider
    a,b=add(client,project,'A'),add(client,project,'B')
    doc_path=f"/api/v1/projects/{project}/canvases/{a['documentId']}"
    doc=client.get(doc_path).json()
    client.post(doc_path+'/save',json={'revision':1,'content':{**doc['content'],'globalPrompt':'A red cube'}})
    chat=client.post(f'/api/v1/projects/{project}/conversations',json={}).json()
    base=f"/api/v1/conversations/{chat['id']}"
    user=client.post(base+'/messages',json={'role':'user','content':'Generate composition','metadata':{'canvas_board':{
        'boardId':a['id'],'documentId':a['documentId'],'documentRevision':2,'boardRevision':1,'name':'A'}}}).json()
    reply=client.post(base+'/reply',json={'message_id':user['id']})
    assert reply.status_code==200,reply.text
    assert client.post(base+'/reply',json={'message_id':user['id']}).json()['id']==reply.json()['id']
    assert provider.calls[0][0]['canvas_board']['prompt']=='A red cube'
    with app.state.session_factory() as session:
        assert list(session.scalars(select(Generation)))==[]
    assert client.get(doc_path).json()['content']['globalPrompt']=='A red cube'


def test_gpu_capacity_is_acquired_before_running_state_and_lease_reenters(canvas_client):
    client, app, project, _ = canvas_client
    a, b = add(client, project, "A"), add(client, project, "B")
    run_a, run_b = generate(client, project, a, "capacity-a"), generate(client, project, b, "capacity-b")
    started, release = threading.Event(), threading.Event()
    worker = JobWorker(app.state.session_factory, app.state.registry, app.state.settings, SimpleNamespace())
    def execute(job_id):
        with gpu_lease(app.state.settings, timeout=0): started.set(); release.wait(5)
        with app.state.session_factory.begin() as session: session.get(Job, job_id).status = "completed"
    worker._execute = execute
    thread = threading.Thread(target=lambda: worker.run_once(run_a["jobId"]))
    thread.start()
    try:
        assert started.wait(5)
        assert worker.run_once(run_b["jobId"]) is None
        with app.state.session_factory() as session:
            assert session.get(Job, run_a["jobId"]).status == "running"
            assert session.get(Job, run_b["jobId"]).status == "queued"
    finally: release.set(); thread.join(5)


def test_existing_workspace_status_reads_do_not_wait_for_an_output_writer(canvas_client):
    import time
    client, app, project, _ = canvas_client
    board = add(client, project, "A")
    receipt = generate(client, project, board, "read-during-ingestion")
    with app.state.session_factory.begin() as session:
        session.get(Job, receipt["jobId"]).status = "running"
    locked, release, failures = threading.Event(), threading.Event(), []
    def writer():
        try:
            with app.state.session_factory.begin() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                session.get(Job, receipt["jobId"]).status_message = "Uncommitted output ingestion"
                session.flush()
                locked.set()
                release.wait(20)
        except Exception as exc:
            failures.append(exc)
    thread = threading.Thread(target=writer)
    thread.start()
    try:
        assert locked.wait(5)
        started = time.monotonic()
        response = client.get(root(project))
        assert response.status_code == 200, response.text
        assert time.monotonic() - started < 2
        current = next(b for b in response.json()["boards"] if b["id"] == board["id"])
        assert current["jobs"][0]["status"] == "running"
        assert current["jobs"][0]["statusMessage"] != "Uncommitted output ingestion"
    finally:
        release.set(); thread.join(5)
    assert not failures


def test_workspace_read_still_maps_documents_added_after_initialization(canvas_client):
    client, _, project, _ = canvas_client
    first = create_canvas(client, project)
    initialized = client.get(root(project)).json()
    second = create_canvas(client, project)
    reopened = client.get(root(project)).json()
    assert {b["documentId"] for b in reopened["boards"]} == {first["id"], second["id"]}
    assert next(b["id"] for b in reopened["boards"] if b["documentId"] == first["id"]) == initialized["boards"][0]["id"]


def test_ready_fifo_blocks_a_later_board_before_claim(canvas_client):
    client, app, project, _ = canvas_client
    a, b = add(client, project, "A"), add(client, project, "B")
    first, second = generate(client, project, a, "fifo-first"), generate(client, project, b, "fifo-second")
    worker = JobWorker(app.state.session_factory, app.state.registry, app.state.settings, SimpleNamespace())
    assert worker.run_once(second["jobId"]) is None
    with app.state.session_factory() as session:
        assert session.get(Job, second["jobId"]).status == "queued"
        assert session.get(Job, first["jobId"]).status == "queued"


def test_contract_tampering_blocks_before_provider_execution(canvas_client):
    from darius_api.atomic_files import atomic_json
    client, app, project, _ = canvas_client
    board = add(client, project, "Protected")
    run = generate(client, project, board, "protected-contract")
    with app.state.session_factory() as session:
        workflow_id = session.get(Job, run["jobId"]).input_payload["workflow_id"]
    contract = app.state.registry.get(workflow_id)
    atomic_json(app.state.settings.workflow_definitions_dir / (workflow_id + ".json"), contract.model_copy(update={"requires_approval": False}).model_dump())
    app.state.registry.load()
    def never(*a, **k): raise AssertionError("Tampered contract reached provider")
    worker = JobWorker(app.state.session_factory, app.state.registry, app.state.settings, SimpleNamespace(execute=never))
    worker.run_once(run["jobId"])
    with app.state.session_factory() as session:
        job = session.get(Job, run["jobId"])
        assert job.status == "failed" and "contract changed" in job.error_detail


def test_canvas_chat_blocks_generic_graph_preparation(canvas_client):
    from darius_api.comfy_assistant import ComfyAssistantTools
    client, app, project, launches = canvas_client
    bridge = ComfyAssistantTools(app.state.settings, app.state.registry, app.state.session_factory)
    bridge.canvas_target = {"boardId": "a"}
    for operation in ("prepare_graph", "prepare_workflow", "queue_local_render", "upload_asset"):
        assert bridge.call({"operation": operation, "arguments": {}})["error_code"] == "canvas_snapshot_required"
    assert not launches


def test_thumbnail_only_cache_is_reused_across_requests(canvas_client, monkeypatch, tmp_path):
    from darius_api.services import ensure_media_thumbnail
    client, app, project, _ = canvas_client
    board = add(client, project, "Thumbnail")
    run = generate(client, project, board, "thumbnail-cache"); source = fake_result(app, project, run)
    image = tmp_path / "thumbnail.jpg"; image.write_bytes(b"mock thumbnail file")
    calls = []
    def create(sf, settings, asset_id, *, thumbnail_only=False):
        assert thumbnail_only; calls.append(asset_id)
        asset = Asset(id="thumbnail", project_id=project, kind="image", role="derivative", path=str(image), content_hash="b"*64,
            mime_type="image/jpeg", provider="ffmpeg", metadata_json={"source_asset_id": source, "derivative_type": "thumbnail"})
        with sf.begin() as session: session.add(asset)
        return [asset], []
    monkeypatch.setattr("darius_api.services.create_media_derivatives", create)
    assert ensure_media_thumbnail(app.state.session_factory, app.state.settings, source)[0][0].id == "thumbnail"
    assert ensure_media_thumbnail(app.state.session_factory, app.state.settings, source)[0][0].id == "thumbnail"
    assert calls == [source]


def test_missing_contract_fails_one_job_without_stalling_queue(canvas_client, monkeypatch):
    client, app, project, _ = canvas_client
    board = add(client, project, "Unavailable")
    run = generate(client, project, board, "missing-contract")
    def missing(key): raise KeyError("Captured workflow is unavailable")
    monkeypatch.setattr(app.state.registry, "get", missing)
    worker = JobWorker(app.state.session_factory, app.state.registry, app.state.settings, SimpleNamespace())
    assert worker.run_once(run["jobId"]) == run["jobId"]
    with app.state.session_factory() as session:
        job = session.get(Job, run["jobId"])
        assert job.status == "failed" and job.error_code == "workflow_unavailable"


def test_duplicates_stay_near_source_preserve_card_size_and_cascade(canvas_client):
    client, _, project, _ = canvas_client
    source = add(client, project, "Source", x=-1200, y=870)
    workspace = client.get(root(project)).json()
    placement = next(p for p in workspace["placements"] if p["boardId"] == source["id"])
    placement.update(displayWidth=640, displayHeight=390)
    assert client.post(root(project) + "/layout", json={"revision": workspace["revision"], "placements": workspace["placements"]}).status_code == 200
    copies = [add(client, project, "Copy", duplicateBoardId=source["id"], x=99999, y=-99999) for _ in range(2)]
    placements = client.get(root(project)).json()["placements"]
    for index, copy in enumerate(copies, 1):
        actual = next(p for p in placements if p["boardId"] == copy["id"])
        assert actual["x"] == -1200 + index * 48
        assert actual["y"] == 870 + index * 48
        assert (actual["displayWidth"], actual["displayHeight"]) == (640, 390)


def test_receipt_lookup_is_read_only_and_project_scoped(canvas_client):
    client, _, project, _ = canvas_client
    board = add(client, project, "A")
    path = f"/api/v1/projects/{project}/canvases/{board['documentId']}"
    assert client.get(path + "/requests/missing-key").json() is None
    receipt = generate(client, project, board, key="lookup-original")
    assert client.get(path + "/requests/lookup-original").json()["jobId"] == receipt["jobId"]
    before = client.get(path).json()
    assert client.get(path.replace(project, "foreign-project") + "/requests/lookup-original").status_code == 404
    assert client.get(path).json() == before
