from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from darius_api import canvas_fibo as fibo
from darius_api.canvas_document import CanvasContent, CanvasRegion, Artboard, PRESETS, dimensions, compile_regions
from darius_api.canvas_moss import digest
from darius_api.canvas_api import completed
from darius_api.database import CanvasGenerationRecord as Generation, Job, Asset
from test_canvas import canvas_client
from test_media_backend import settings_for
from test_moss_workspace import add, generate, root


def test_fibo_geometry_order_text_palette_and_hidden_parent(tmp_path):
    group = CanvasRegion(id="group", name="Group", kind="group", x=.25, y=.1, width=.5, height=.8)
    text = CanvasRegion(id="text", parentId="group", name="Text", kind="text", x=.5, y=.25, width=.25, height=.5,
        text='"你好"\nIt\'s café', description="Gold lettering", palette=["#d4a574"], order=1)
    obj = CanvasRegion(id="obj", name="Object", kind="character", x=.05, y=.2, width=.3, height=.4, description="A robot", order=2)
    content = CanvasContent(globalPrompt="A poster", regions=[obj, text, group])
    graph, p = fibo.compile_graph(settings_for(tmp_path), content, 64, fibo.FAST)
    assert p["regionIndexMap"] == ["text", "obj"]
    assert p["normalizedElements"] == [
        {"type": "text", "bbox": [300, 500, 700, 625], "text": text.text, "desc": "Gold lettering", "color_palette": ["#D4A574"]},
        {"type": "obj", "bbox": [200, 50, 600, 350], "desc": "A robot"}]
    assert str(p["normalizedElements"][0]) in p["conditioningPrompt"]
    assert graph["4"]["inputs"]["prompt"] == ["20", 0]
    assert not {"vae", "images", "image_1"} & graph["4"]["inputs"].keys()
    assert graph["17"]["inputs"]["last_incoming"] == {"__value__": []}
    group.visible = False
    _, hidden = fibo.compile_graph(settings_for(tmp_path), content, 64)
    assert hidden["regionIndexMap"] == ["obj"]


def test_nonsquare_tlbr_uses_each_axis_not_xywh():
    boxes = [{"x": 384, "y": 128, "width": 768, "height": 256,
              "metadata": {"type": "obj", "desc": "rectangle", "palette": []}}]
    assert fibo.elements_for(boxes, 1536, 1024)[0]["bbox"] == [125, 250, 375, 750]


def test_turbo_weights_and_original_example_recovery(tmp_path):
    settings = settings_for(tmp_path)
    imported = fibo.example(settings)
    content = CanvasContent.model_validate(imported["content"])
    assert len(content.regions) == 2
    assert content.regions[0].palette == ["#d4a574"]
    assert content.regions[0].x == .25 and content.regions[0].height == 448/1024
    turbo, p = fibo.compile_graph(settings, content, 64, fibo.FAST)
    legacy, old = fibo.compile_graph(settings, content, 64, fibo.LEGACY_FAST)
    assert turbo["26"]["inputs"]["unet_name"] == "fibo2_edit_turbo_int8_convrot.safetensors"
    assert legacy["26"]["inputs"]["unet_name"] == "fibo2_dev_int8_convrot.safetensors"
    assert p["profileVersion"] == 2
    assert p["conditioningPrompt"] == old["conditioningPrompt"]
    assert fibo.compile_graph(settings, content, 64, fibo.DEV, old)[1]["conditioningPrompt"] == p["conditioningPrompt"]


def test_profiles_preserve_sources_and_exact_snapshot_promotion(tmp_path):
    settings = settings_for(tmp_path)
    content = CanvasContent(globalPrompt="Scene\nSCENE / STYLE: literal user words", regions=[])
    fast, p = fibo.compile_graph(settings, content, 2**64-1, fibo.FAST)
    dev, promoted = fibo.compile_graph(settings, content, str(2**64-1), fibo.DEV, p)
    assert fast["23"]["inputs"]["steps"] == 4 and dev["6"]["inputs"]["steps"] == 30
    assert fast["23"]["inputs"]["cfg"] == 1 and dev["6"]["inputs"]["cfg"] == 5
    assert p["conditioningPrompt"] == promoted["conditioningPrompt"]
    assert p["compositionInputHash"] == promoted["compositionInputHash"]
    assert p["executionProfileHash"] != promoted["executionProfileHash"]
    for broken in (dict(p, compilerVersion="new-version"), dict(p, conditioningPrompt="different"), dict(p, documentSnapshot={})):
        with pytest.raises(ValueError, match="compatible"):
            fibo.compile_graph(settings, content, 2**64-1, fibo.DEV, broken)
    # The two source files and API conversion are independent from working copies.
    for profile in fibo.PROFILES:
        manifest, _, _ = fibo.artifacts(settings, profile)
        import hashlib
        source = settings.repository_root / "workflows/defaults" / manifest["sourceFile"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["sourceUiDigest"]


def mark_complete(app, project, receipt):
    with app.state.session_factory.begin() as session:
        row = session.get(Generation, receipt["id"])
        job = session.get(Job, row.job_id)
        asset = Asset(id=row.id, project_id=project, kind="image", role="generation", path=f"/test/{row.id}.png",
            content_hash="a"*64, mime_type="image/png", provider="local-comfyui", workflow_run_id=job.id)
        session.add(asset); session.flush()
        job.status = "completed"; job.output_asset_ids = [asset.id]
        completed(session, job, {"canvas_conditioning_prompt": row.provenance_json["conditioningPrompt"]})


def test_large_seed_retained_old_revision_promotes_idempotently(canvas_client, monkeypatch):
    client, app, project, launches = canvas_client
    monkeypatch.setattr(fibo, "readiness", lambda *a, **k: {"ready": True})
    board = add(client, project, settings={"adapterVersion": fibo.FAST, "seed": str(2**64-1)})
    receipt = generate(client, project, board, "fibo-fast-one")
    assert receipt["seed"] == str(2**64-1)
    mark_complete(app, project, receipt)
    path = f"/api/v1/projects/{project}/canvases/{board['documentId']}"
    doc = client.get(path).json(); newer = deepcopy(doc["content"]); newer["globalPrompt"] = "A completely different scene"
    saved = client.post(path + "/save", json={"revision": doc["revision"], "content": newer}).json()
    payload = {"revision": receipt["revision"], "idempotencyKey": "promote-old-preview", "approved": True,
        "boardId": board["id"], "boardRevision": board["revision"], "profileId": fibo.DEV,
        "promotedFromGenerationId": receipt["id"], "seed": receipt["seed"]}
    response = client.post(path + "/generate", json=payload)
    assert response.status_code == 200, response.text
    promoted = response.json()
    assert promoted["provenance"]["documentSnapshot"] == doc["content"]
    assert promoted["provenance"]["conditioningPrompt"] == receipt["provenance"]["conditioningPrompt"]
    assert promoted["seed"] == str(2**64-1)
    assert client.post(path + "/generate", json=payload).json() == promoted
    assert len(launches) == 2
    mark_complete(app, project, promoted)
    current = client.get(path).json()
    assert current["revision"] == saved["revision"] and current["content"] == newer
    assert current["activeGenerationId"] == receipt["id"]
    assert len({asset for g in current["generations"] for asset in g["assetIds"]}) == 2
    payload["profileId"] = fibo.FAST
    assert client.post(path + "/generate", json=payload).status_code == 409


@pytest.mark.parametrize("source_problem", ["running", "dev", "snapshot", "compiler", "receipt", "wrong-board", "missing-assets"])
def test_invalid_promotion_never_enqueues(canvas_client, monkeypatch, source_problem):
    client, app, project, launches = canvas_client
    monkeypatch.setattr(fibo, "readiness", lambda *a, **k: {"ready": True})
    board = add(client, project, settings={"adapterVersion": fibo.FAST})
    receipt = generate(client, project, board, "source-preview-one")
    mark_complete(app, project, receipt)
    with app.state.session_factory.begin() as session:
        row = session.get(Generation, receipt["id"]); job = session.get(Job, row.job_id)
        p = deepcopy(row.provenance_json)
        if source_problem == "running": job.status = "running"
        if source_problem == "dev": p["profileId"] = fibo.DEV
        if source_problem == "snapshot": p.pop("documentSnapshot")
        if source_problem == "compiler": p["compilerVersion"] = "future-compiler"
        if source_problem == "receipt": p["conditioningPromptVerified"] = False
        if source_problem == "wrong-board": p["board"]["boardId"] = "elsewhere"
        if source_problem == "missing-assets": job.output_asset_ids = []
        row.provenance_json = p
    path = f"/api/v1/projects/{project}/canvases/{board['documentId']}/generate"
    result = client.post(path, json={"revision": receipt["revision"], "idempotencyKey": "invalid-promotion", "approved": True,
        "boardId": board["id"], "boardRevision": board["revision"], "promotedFromGenerationId": receipt["id"]})
    assert result.status_code == 422, result.text
    assert len(launches) == 1


def test_standalone_dev_no_preview_and_shared_preset_boundary(canvas_client, monkeypatch, tmp_path):
    client, _, project, launches = canvas_client
    monkeypatch.setattr(fibo, "readiness", lambda *a, **k: {"ready": True})
    board = add(client, project, settings={"adapterVersion": fibo.DEV})
    result = generate(client, project, board, "standalone-dev")
    assert result["provenance"]["profileId"] == fibo.DEV and len(launches) == 1
    assert "promotedFromGenerationId" not in result["provenance"]
    engine = client.get("/api/v1/canvas/engine?profile=" + fibo.DEV).json()
    moss = client.get("/api/v1/canvas/engine").json()
    assert engine["presets"] == moss["presets"]
    bad = CanvasContent(globalPrompt="A cube")
    bad.artboard.width = 1536
    with pytest.raises(ValueError, match="selected Canvas preset"):
        fibo.compile_graph(settings_for(tmp_path), bad, 1)


@pytest.mark.parametrize("preset", list(PRESETS))
@pytest.mark.parametrize("profile", [fibo.FAST, fibo.DEV, fibo.LEGACY_FAST])
def test_fibo_all_canvas_sizes_share_one_geometry_and_output_size(tmp_path, preset, profile):
    width, height = dimensions(preset)
    content = CanvasContent(artboard=Artboard(preset=preset, width=width, height=height), globalPrompt="A red cube",
        regions=[CanvasRegion(id="cube", name="Cube", x=.125, y=.25, width=.5, height=.375, description="A red cube")])
    graph, p = fibo.compile_graph(settings_for(tmp_path), content, 42, profile)
    assert (graph["17"]["inputs"]["width"], graph["17"]["inputs"]["height"]) == (width, height)
    assert (graph["4"]["inputs"]["width"], graph["4"]["inputs"]["height"]) == (width, height)
    assert (p["width"], p["height"]) == (width, height)
    assert p["normalizedElements"][0]["bbox"] == [250, 125, 625, 625]
    assert graph["17"]["inputs"]["editor_state"]["__value__"][0]["width"] == width*.5
    dev, promoted = fibo.compile_graph(settings_for(tmp_path), content, 42, fibo.DEV,
        p if profile in {fibo.FAST, fibo.LEGACY_FAST} else None)
    assert (dev["4"]["inputs"]["width"], dev["4"]["inputs"]["height"]) == (width, height)
    assert promoted["compositionInputHash"] == p["compositionInputHash"]


@pytest.mark.parametrize("preset", ["wide", "portrait"])
def test_promoting_nonsquare_preview_keeps_historical_size_after_draft_resize(canvas_client, monkeypatch, preset):
    client, app, project, launches = canvas_client
    monkeypatch.setattr(fibo, "readiness", lambda *a, **k: {"ready": True})
    width, height = dimensions(preset)
    content = CanvasContent(artboard=Artboard(preset=preset, width=width, height=height), globalPrompt="A cube")
    board = add(client, project, content=content.model_dump(), settings={"adapterVersion": fibo.FAST, "seed": "42"})
    receipt = generate(client, project, board, "nonsquare-preview")
    mark_complete(app, project, receipt)
    base = f"/api/v1/projects/{project}/canvases/{board['documentId']}"
    current = client.get(base).json()
    current["content"]["artboard"] = Artboard().model_dump()
    assert client.post(base + "/save", json={"revision": 1, "content": current["content"]}).status_code == 200
    response = client.post(base + "/generate", json={"revision": 1, "idempotencyKey": "promote-nonsquare-preview", "approved": True,
        "boardId": board["id"], "boardRevision": board["revision"], "profileId": fibo.DEV, "promotedFromGenerationId": receipt["id"]})
    assert response.status_code == 200, response.text
    assert (response.json()["provenance"]["width"], response.json()["provenance"]["height"]) == (width, height)
    assert client.get(base).json()["content"]["artboard"]["preset"] == "square"
    assert len(launches) == 2


@pytest.mark.parametrize("minimum,expected", [(0, True), (1, False)])
def test_fibo_zero_image_validation_is_proven_by_live_schema(monkeypatch, minimum, expected):
    import json
    from darius_api.comfy_preflight import accept_zero_reference_qwen_warning
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self):
            return json.dumps({"TextEncodeFibo2": {"input": {"required": {
                "images": ["COMFY_AUTOGROW_V3", {"template": {"min": minimum}}]}}}}).encode()
    class Opener:
        def open(self, url, **k):
            assert url.endswith("/object_info/TextEncodeFibo2")
            return Response()
    monkeypatch.setattr("darius_api.comfy_preflight.urllib.request.build_opener", lambda *a: Opener())
    graph = {"4": {"class_type": "TextEncodeFibo2", "inputs": {"prompt": "A cube"}}}
    validation = {"valid": False, "errors": [{"node_id": "4", "field": "images", "code": "autogrow_no_slots"}]}
    result = accept_zero_reference_qwen_warning(validation, graph, "http://127.0.0.1:8188", node_type="TextEncodeFibo2")
    assert result["valid"] is expected
    other = {"valid": False, "errors": [*validation["errors"], {"node_id": "4", "field": "clip", "code": "required_input_missing"}]}
    assert not accept_zero_reference_qwen_warning(other, graph, "http://127.0.0.1:8188", node_type="TextEncodeFibo2")["valid"]
