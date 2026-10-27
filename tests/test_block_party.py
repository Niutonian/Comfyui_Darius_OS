import io
import json
import stat
import zipfile
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from darius_api import block_party as bp
from darius_api.block_party_readiness import check_readiness
from darius_api.main import create_app
from darius_api.providers import ComfyMcpProvider
from darius_api.workflow_registration import register, registered, compiled, cache_path
from darius_api.workflow_catalog import discover_workflows
from test_media_backend import settings_for


@pytest.fixture
def package_setup(tmp_path, monkeypatch):
    defaults = tmp_path / "defaults"; defaults.mkdir()
    definitions = tmp_path / "definitions"; definitions.mkdir()
    root = tmp_path / "ComfyUI"; root.mkdir()
    (root / "main.py").write_text("")
    (root / "folder_paths.py").write_text("")
    settings = replace(settings_for(tmp_path), workflow_definitions_dir=definitions,
                       comfy_workflow_defaults_root=defaults, block_party_comfy_root=root)
    graph = {
        "text": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "An old example subject"}},
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"text": ["text", 0]}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality"}, "_meta": {"title": "Negative prompt"}},
        "sample": {"class_type": "KSampler", "inputs": {"positive": ["positive", 0], "negative": ["negative", 0], "seed": 5, "steps": 20}},
        "size": {"class_type": "PrimitiveInt", "inputs": {"value": 512}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["sample", 0], "filename_prefix": "example"}},
    }
    manifest = {"name": "Party still", "workflows": [{"name": "default", "file": "workflow.api.json"}],
        "inputs": [], "outputs": [{"name": "image_0", "node_id": "save", "class_type": "SaveImage"}],
        "models": [], "nodes": [], "parameters": [
            {"name": "prompt", "node_id": "text", "class_type": "PrimitiveStringMultiline", "key": "value", "type": "string", "default": graph["text"]["inputs"]["value"]},
            {"name": "width", "node_id": "size", "class_type": "PrimitiveInt", "key": "value", "type": "integer", "default": 512, "min": 256, "max": 1024, "step": 64},
            {"name": "seed", "node_id": "sample", "class_type": "KSampler", "key": "seed", "type": "seed", "default": "random"},
        ]}
    monkeypatch.setattr(ComfyMcpProvider, "live_node_schemas", lambda self, graph: {
        node["class_type"]: {"python_module": "nodes"} for node in graph.values()})
    return settings, manifest, graph


def archive(manifest, graph, extras=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("party/manifest.json", json.dumps(manifest))
        z.writestr("party/workflow.api.json", json.dumps(graph))
        for name, value in (extras or {}).items():
            z.writestr(name, value)
    return output.getvalue()


def test_aspect_ratio_parameter_does_not_compete_with_exposed_scene_prompt(package_setup):
    settings, declared, graph = package_setup
    declared["parameters"][0]["name"] = "value_2"
    graph["ratio"] = {"class_type": "ResolutionSelector", "inputs": {"aspect_ratio": "1:1 (Square)"}}
    declared["parameters"].append({"name": "aspect_ratio", "node_id": "ratio", "class_type": "ResolutionSelector",
        "key": "aspect_ratio", "type": "string", "default": "1:1 (Square)"})
    result = bp.import_zip(settings, archive(declared, graph))
    contract = result["registration"]
    assert contract["status"] == "ready" and contract["scene_slots"] == ["text.value"]
    assert contract["setting_slots"]["aspect_ratio"] == ["ratio.aspect_ratio"]
    assert "ratio.aspect_ratio" not in {field["slot"] for field in contract["fields"]}
    with pytest.raises(bp.PackageError):
        register(settings, result["workflow_id"], graph, roles={"ratio.aspect_ratio": "scene"})
    assert register(settings, result["workflow_id"], graph, roles={"ratio.aspect_ratio": "preserve"})["status"] == "ready"
    legacy = register(settings, result["workflow_id"], graph, roles={"text.value": "unresolved", "ratio.aspect_ratio": "unresolved"})
    assert legacy["status"] == "needs_mapping" and legacy["unresolved_slots"] == ["text.value"]
    assert graph["ratio"]["inputs"]["aspect_ratio"] == "1:1 (Square)"


def test_unknown_string_parameter_still_requires_mapping(package_setup):
    settings, declared, graph = package_setup
    graph["unknown"] = {"class_type": "CustomSelector", "inputs": {"mode": "preserve this"}}
    declared["parameters"].append({"name": "mode", "node_id": "unknown", "class_type": "CustomSelector",
        "key": "mode", "type": "string", "default": "preserve this"})
    result = bp.import_zip(settings, archive(declared, graph))
    assert result["registration"]["status"] == "needs_mapping"
    assert "unknown.mode" in result["registration"]["unresolved_slots"]


def test_chat_list_workflows_reads_imported_darius_bases_not_comfy_cli(package_setup, monkeypatch):
    from darius_api.comfy_assistant import ComfyAssistantTools
    from darius_api.workflows import WorkflowRegistry
    settings, declared, graph = package_setup
    result = bp.import_zip(settings, archive(declared, graph))
    registry = WorkflowRegistry(settings.workflow_definitions_dir)
    registry.load()
    bridge = ComfyAssistantTools(settings, registry, None)
    monkeypatch.setattr(bridge, "_run", lambda *a: pytest.fail("A Darius recipe query must not use Comfy's unrelated catalog"))
    receipt = bridge.call({"operation": "list_workflows", "arguments": {"name": "Party_still", "limit": 1}})
    assert [w["workflow_id"] for w in receipt["workflows"]] == [result["workflow_id"]]
    assert "graph" not in receipt["workflows"][0] and receipt["total"] == 1
    assert bridge.call({"operation": "list_workflows", "arguments": {"name": "missing"}})["workflows"] == []


def test_import_is_declarative_idempotent_and_discoverable(package_setup):
    settings, manifest, graph = package_setup
    result = bp.import_zip(settings, archive(manifest, graph, {"party/run.py": "raise Exception('must not run')", "party/input/example.png": "not an asset", "party/state/prepared.json": '{"approved":true}'}))
    workflow = result["workflow_id"]
    assert result["registration"]["scene_slots"] == ["text.value"]
    assert result["registration"]["setting_slots"]["width"] == ["size.value"]
    assert bp.import_zip(settings, archive(manifest, graph))["already_imported"]
    assert [item["workflow_id"] for item in discover_workflows(settings, output_kind="image")["workflows"]] == [workflow]
    assert json.loads((settings.comfy_workflow_defaults_root / workflow).read_text()) == graph
    assert not list(settings.comfy_workflow_defaults_root.rglob("*.py"))
    assert not list(settings.data_dir.rglob("example.png"))
    assert registered(settings, workflow) is not None
    assert check_readiness(settings, workflow)["ready"]


@pytest.mark.parametrize("bad", ["../escape.json", "/absolute", "C:/escape", "party/../escape", "party\\escape", "party/space. "])
def test_import_rejects_unsafe_paths_without_publication(package_setup, bad):
    settings, manifest, graph = package_setup
    payload = archive(manifest, graph, {bad: "bad"})
    if "\\" in bad:
        # zipfile normalizes Windows separators while writing; corrupt the raw
        # archive names deliberately so the reader sees the unsafe original.
        payload = payload.replace(bad.replace("\\", "/").encode(), bad.encode())
    with pytest.raises(bp.PackageError, match="unsafe path"):
        bp.import_zip(settings, payload)
    assert not list(settings.comfy_workflow_defaults_root.rglob("*.json"))


def test_zip_links_and_duplicate_keys_are_rejected(package_setup):
    settings, manifest, graph = package_setup
    out = io.BytesIO(archive(manifest, graph))
    with zipfile.ZipFile(out, "a") as z:
        info = zipfile.ZipInfo("party/link"); info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, "/etc/passwd")
    with pytest.raises(bp.PackageError, match="Links"):
        bp.import_zip(settings, out.getvalue())
    with pytest.raises(bp.PackageError):
        bp._json(b'{"name":1,"name":2}')


@pytest.mark.parametrize("change", ["node", "default", "connection", "secret", "seed_target"])
def test_import_rejects_inconsistent_or_sensitive_contract(package_setup, change):
    settings, manifest, graph = package_setup
    if change == "node": manifest["parameters"][0]["class_type"] = "FakeNode"
    if change == "default": manifest["parameters"][0]["default"] = "different"
    if change == "connection": manifest["parameters"][0].update(node_id="positive", class_type="CLIPTextEncode", key="text", default=["text", 0])
    if change == "secret": manifest["api_key"] = "private"
    if change == "seed_target": manifest["parameters"][2].update(node_id="sample", key="steps", default=20)
    with pytest.raises(bp.PackageError): bp.import_zip(settings, archive(manifest, graph))


def test_model_dependencies_cannot_be_omitted(package_setup):
    settings, manifest, graph = package_setup
    graph["loader"] = {"class_type": "UNETLoader", "inputs": {"unet_name": "secret-model.safetensors"}}
    with pytest.raises(bp.PackageError, match="absent from the dependency manifest"):
        bp.import_zip(settings, archive(manifest, graph))


@pytest.mark.parametrize("saved_seed", [931694587472718, 279756367733420, 2**64 - 1])
def test_random_seed_accepts_legacy_graph_seed_but_generates_in_declared_range(package_setup, saved_seed):
    settings, manifest, graph = package_setup
    graph["sample"]["inputs"]["seed"] = saved_seed
    result = bp.import_zip(settings, archive(manifest, graph))
    prepared = deepcopy(graph)
    bp.prepare_declared_seeds(prepared, result["registration"], "randomize", {})
    assert 0 <= prepared["sample"]["inputs"]["seed"] < 2**32
    assert json.loads((settings.comfy_workflow_defaults_root / result["workflow_id"]).read_text())["sample"]["inputs"]["seed"] == saved_seed


@pytest.mark.parametrize("bad_seed", [True, "931694587472718", 1.5, None])
def test_random_seed_still_requires_integer_graph_target(package_setup, bad_seed):
    settings, manifest, graph = package_setup
    graph["sample"]["inputs"]["seed"] = bad_seed
    with pytest.raises(bp.PackageError): bp.import_zip(settings, archive(manifest, graph))


def test_explicit_seed_and_override_still_obey_declared_range(package_setup):
    settings, manifest, graph = package_setup
    result = bp.import_zip(settings, archive(manifest, graph))
    with pytest.raises(bp.PackageError, match="outside"):
        bp.enforce_overrides(result["registration"], {"sample.seed": 2**32}, {})
    graph["sample"]["inputs"]["seed"] = 931694587472718
    manifest["parameters"][2]["default"] = 931694587472718
    with pytest.raises(bp.PackageError, match="outside"):
        bp.import_zip(settings, archive(manifest, graph))


def test_changed_graph_or_manifest_invalidates_registration(package_setup):
    settings, manifest, graph = package_setup
    result = bp.import_zip(settings, archive(manifest, graph))
    workflow = result["workflow_id"]
    path = settings.comfy_workflow_defaults_root / workflow
    changed = deepcopy(graph); changed["sample"]["inputs"]["steps"] = 21
    path.write_text(json.dumps(changed))
    assert compiled(settings, workflow) is None
    with pytest.raises(bp.PackageError, match="changed"):
        bp.load(settings, workflow)
    assert discover_workflows(settings, output_kind="image")["workflows"] == []
    with pytest.raises(bp.PackageError): bp.import_zip(settings, archive(manifest, graph))


def test_exposed_inputs_bounds_and_fixed_seed_protection(package_setup):
    settings, manifest, graph = package_setup
    result = bp.import_zip(settings, archive(manifest, graph)); contract = result["registration"]
    bp.enforce_overrides(contract, {"text.value": "A new subject", "size.value": 768}, {})
    for overrides in ({"sample.steps": 40}, {"size.value": 300}, {"size.value": 2048}, {"size.value": True}):
        with pytest.raises(bp.PackageError): bp.enforce_overrides(contract, overrides, {})
    graph["fixed"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": 99}}
    bp.prepare_declared_seeds(graph, contract, "randomize", {})
    assert graph["fixed"]["inputs"]["noise_seed"] == 99
    assert type(graph["sample"]["inputs"]["seed"]) is int
    with pytest.raises(bp.PackageError): register(settings, result["workflow_id"], bp.load(settings, result["workflow_id"])[1], roles={"negative.text": "scene"})


def test_readiness_hashes_declared_models_and_detects_missing_changed_files(package_setup):
    settings, manifest, graph = package_setup
    content = b"a fake model; never loaded"
    manifest["models"] = [{"filename": "model.safetensors", "folder": "unet", "sha256": sha256(content).hexdigest()}]
    result = bp.import_zip(settings, archive(manifest, graph)); workflow = result["workflow_id"]
    assert check_readiness(settings, workflow)["issues"][0]["code"] == "missing_model"
    model = settings.block_party_comfy_root / "models/diffusion_models/model.safetensors"
    model.parent.mkdir(parents=True); model.write_bytes(content)
    assert check_readiness(settings, workflow)["ready"]
    model.write_bytes(b"another version")
    assert check_readiness(settings, workflow)["issues"][0]["code"] == "model_hash_mismatch"


def test_media_slots_must_be_complete_and_no_bundled_reference_fallback(package_setup):
    settings, manifest, graph = package_setup
    graph["reference"] = {"class_type": "LoadImage", "inputs": {"image": "example.png"}}
    with pytest.raises(bp.PackageError, match="every"):
        bp.import_zip(settings, archive(manifest, graph))
    manifest["inputs"] = [{"name": "hero", "node_id": "reference", "class_type": "LoadImage", "key": "image", "extensions": [".png"]}]
    result = bp.import_zip(settings, archive(manifest, graph))
    with pytest.raises(bp.PackageError, match="Bind every"):
        bp.enforce_overrides(result["registration"], {}, {})
    bp.enforce_overrides(result["registration"], {}, {"reference.image": "project-asset"})


def test_import_api_never_creates_jobs_or_changes_default_selection(package_setup):
    settings, manifest, graph = package_setup
    with TestClient(create_app(settings)) as client:
        before = client.get("/api/v1/settings/workflow-defaults").json()
        response = client.post("/api/v1/workflow-recipes/block-party/import", files={"file": ("party.zip", archive(manifest, graph), "application/zip")})
        assert response.status_code == 201, response.text
        workflow = response.json()["workflow_id"]
        assert any(item["id"] == workflow for item in client.get("/api/v1/workflow-recipes").json()["workflows"])
        report = client.post("/api/v1/workflow-recipes/block-party/readiness", json={"workflow_id": workflow})
        assert report.status_code == 200 and report.json()["ready"]
        assert client.get("/api/v1/jobs").json() == []
        assert client.get("/api/v1/settings/workflow-defaults").json() == before


def test_node_pins_modified_packs_and_loaded_origins_are_checked(package_setup, monkeypatch):
    from darius_api import block_party_readiness as ready
    settings, manifest, graph = package_setup
    graph["custom"] = {"class_type": "PartyHelper", "inputs": {}}
    manifest["nodes"] = [{"name": "PartyNodes", "commit": "a" * 40, "class_types": ["PartyHelper"]}]
    pack = settings.block_party_comfy_root / "custom_nodes/PartyNodes"; pack.mkdir(parents=True)
    result = bp.import_zip(settings, archive(manifest, graph)); workflow = result["workflow_id"]
    state = {"commit": "a" * 40, "dirty": "", "origin": "custom_nodes.PartyNodes"}
    def git(path, *args):
        if "--show-toplevel" in args: return str(pack)
        return state["commit"] if args[0] == "rev-parse" else state["dirty"]
    monkeypatch.setattr(ready, "_git", git)
    monkeypatch.setattr(ComfyMcpProvider, "live_node_schemas", lambda self, graph: {
        node["class_type"]: {"python_module": state["origin"] if node["class_type"] == "PartyHelper" else "nodes"} for node in graph.values()})
    assert check_readiness(settings, workflow)["ready"]
    state["commit"] = "b" * 40
    assert check_readiness(settings, workflow)["issues"][0]["code"] == "node_revision_mismatch"
    state["commit"], state["dirty"] = "a" * 40, " M helper.py"
    assert check_readiness(settings, workflow)["issues"][0]["code"] == "node_pack_modified"
    state["dirty"], state["origin"] = "", "custom_nodes.spoofed"
    assert check_readiness(settings, workflow)["issues"][0]["code"] == "node_origin_mismatch"


def test_bridge_uses_declared_contract_and_rejects_graph_copy_bypass(package_setup, monkeypatch):
    from darius_api.comfy_assistant import ComfyAssistantTools
    settings, manifest, graph = package_setup
    result = bp.import_zip(settings, archive(manifest, graph)); workflow = result["workflow_id"]
    monkeypatch.setattr("darius_api.comfy_assistant.validate_graph", lambda graph, **kwargs: graph)
    monkeypatch.setattr(ComfyMcpProvider, "validate_api_graph", lambda *args, **kwargs: {"valid": True, "errors": []})
    with TestClient(create_app(settings)) as client:
        project = client.post("/api/v1/projects", json={"name": "Party project"}).json()["id"]
        bridge = ComfyAssistantTools(settings, client.app.state.registry, client.app.state.session_factory, project_id=project)
        inspected = bridge.call({"operation": "inspect_workflow", "arguments": {"workflow_id": workflow}})
        assert "error" not in inspected, inspected
        assert inspected["recipe_manifest"]["block_party"]["parameters"] == manifest["parameters"]
        modified = deepcopy(graph); modified["sample"]["inputs"]["steps"] = 100
        # Reordering JSON keys must not evade the structure check.
        copied = bridge.call({"operation": "prepare_graph", "arguments": {"graph": dict(reversed(list(modified.items()))), "name": "copy"}})
        assert "prepare_workflow" in copied["error"]
        args = {"workflow_id": workflow, "name": "A new garden", "overrides": {"sample.steps": 100}, "output_kind": "image"}
        blocked = bridge.call({"operation": "prepare_workflow", "arguments": args})
        assert "not exposed" in blocked["error"]
        args["overrides"] = {"text.value": "A new garden", "size.value": 768}
        prepared = bridge.call({"operation": "prepare_workflow", "arguments": args})
        assert "error" not in prepared, prepared
        assert prepared["workflow_id"].startswith("assistant-")
        assert json.loads((settings.comfy_workflow_defaults_root / workflow).read_text()) == graph
        assert client.get("/api/v1/jobs").json() == []
