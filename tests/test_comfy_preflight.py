import io
from types import SimpleNamespace
from pathlib import Path
import json
import pytest

from darius_api.comfy_preflight import (accept_zero_reference_qwen_warning,
                                        validate_capability_graph, validate_graph)
from darius_api.local_render import verify_local_graph
from darius_api.providers import ProviderError
from darius_api.providers import ComfyMcpProvider
from darius_api.services import RequestError, _check_workflow_source_assets


def test_rejects_unresolved_reference_before_comfy():
    graph = {"76": {"class_type": "LoadImage", "inputs": {"image": "__REFERENCE__"}}}
    with pytest.raises(ProviderError, match="unresolved"):
        validate_graph(graph, comfy_base_url="http://127.0.0.1:8188", verify_images=False)


def test_normalizes_windows_image_path_and_verifies_visibility(monkeypatch):
    seen = {}

    def view(url, timeout):
        seen["url"] = url
        return io.BytesIO(b"x")

    monkeypatch.setattr("urllib.request.urlopen", view)
    graph = {"137": {"class_type": "LoadImage", "inputs": {"image": "darius\\refs\\shot.png"}}}
    result = validate_graph(graph, comfy_base_url="http://127.0.0.1:8188")
    assert result["137"]["inputs"]["image"] == "darius/refs/shot.png"
    assert "filename=shot.png" in seen["url"]
    assert "subfolder=darius%2Frefs" in seen["url"]


def test_missing_comfy_image_is_reported(monkeypatch):
    def missing(*args, **kwargs):
        raise OSError("not found")

    monkeypatch.setattr("urllib.request.urlopen", missing)
    graph = {"137": {"class_type": "LoadImage", "inputs": {"image": "missing.png"}}}
    with pytest.raises(ProviderError, match="not visible|could not verify"):
        validate_graph(graph, comfy_base_url="http://127.0.0.1:8188")


def test_rejects_h3_keyframes_as_text_to_video():
    graph = {"5": {"class_type": "H3Keyframes", "inputs": {"prompt": "text"}}}
    with pytest.raises(ProviderError, match="H3Keyframes.*requires an image"):
        validate_capability_graph(graph, "text-to-video")


def test_rejects_deleted_workflow_source_asset():
    asset = SimpleNamespace(id="asset-1", project_id="project-1", kind="image", path="Z:/deleted/image.png")

    class Session:
        def get(self, model, asset_id):
            return asset if asset_id == "asset-1" else None

    contract = SimpleNamespace(source_asset_ids=["asset-1"])
    with pytest.raises(RequestError, match="missing from managed storage"):
        _check_workflow_source_assets(Session(), contract, "project-1", request_error=True)


def test_qwen_zero_reference_warning_is_waived_only_for_live_optional_schema(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            import json
            return json.dumps({"TextEncodeQwenImage21": {
                "api_node": False,
                "input": {"required": {"images": ["COMFY_AUTOGROW_V3", {"template": {"min": 0}}]}},
            }}).encode()
    class Opener:
        def open(self, *args, **kwargs):
            return Response()
    monkeypatch.setattr("darius_api.comfy_preflight.urllib.request.build_opener", lambda *a: Opener())
    graph = {"459:452": {"class_type": "TextEncodeQwenImage21", "inputs": {"prompt": "landscape"}}}
    validation = {"valid": False, "error_count": 2, "errors": [
        {"node_id": "459:452", "field": "images", "code": "autogrow_no_slots"},
        {"node_id": "another", "field": "prompt", "code": "required_input_missing"},
    ]}

    result = accept_zero_reference_qwen_warning(validation, graph, "http://127.0.0.1:8188")

    assert result["valid"] is False
    assert result["error_count"] == 1
    assert result["errors"] == [validation["errors"][1]]
    assert validation["errors"][0]["code"] == "autogrow_no_slots"


def test_qwen_zero_reference_warning_is_not_waived_when_schema_requires_slot(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            import json
            return json.dumps({"TextEncodeQwenImage21": {
                "api_node": False,
                "input": {"required": {"images": ["COMFY_AUTOGROW_V3", {"template": {"min": 1}}]}},
            }}).encode()
    class Opener:
        def open(self, *args, **kwargs):
            return Response()
    monkeypatch.setattr("darius_api.comfy_preflight.urllib.request.build_opener", lambda *a: Opener())
    graph = {"459:452": {"class_type": "TextEncodeQwenImage21", "inputs": {}}}
    validation = {"valid": False, "errors": [
        {"node_id": "459:452", "field": "images", "code": "autogrow_no_slots"},
    ]}

    assert accept_zero_reference_qwen_warning(validation, graph, "http://127.0.0.1:8188") is validation


def test_unrecognized_custom_node_remains_blocked_from_local_auto_render():
    contract = SimpleNamespace(
        execution_provider="local-comfyui",
        runtime_mapping=SimpleNamespace(api_format=True),
        enabled=True,
        estimated_cost=None,
    )
    graph = {"1": {"class_type": "UnreviewedCustomNode", "inputs": {}}}

    with pytest.raises(ProviderError, match="unverified or external nodes"):
        verify_local_graph(SimpleNamespace(comfyui_base_url="http://127.0.0.1:8188"), contract, graph)


def test_historical_template_image_is_blocked_at_render_time():
    contract = SimpleNamespace(
        execution_provider="local-comfyui", runtime_mapping=SimpleNamespace(api_format=True),
        enabled=True, estimated_cost=None, source_asset_ids=[],
    )
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "someone-elses-template.png"}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "test"}},
    }

    with pytest.raises(ProviderError, match="without active-project provenance"):
        verify_local_graph(SimpleNamespace(comfyui_base_url="http://127.0.0.1:8188"), contract, graph)


def test_api_workflow_validation_uses_live_schema_snapshot_without_submission(tmp_path, monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json.dumps({"TextEncodeQwenImage21": {
                "api_node": False,
                "input": {"required": {"images": ["COMFY_AUTOGROW_V3", {"template": {"min": 0}}]}},
            }}).encode()

    class Opener:
        def open(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("darius_api.providers.urllib.request.build_opener", lambda *a: Opener())
    monkeypatch.setattr("darius_api.comfy_preflight.urllib.request.build_opener", lambda *a: Opener())
    settings = SimpleNamespace(comfyui_base_url="http://127.0.0.1:8188", comfy_mcp_command="comfy",
                               comfy_mcp_args=())
    provider = ComfyMcpProvider(settings)
    validation = {"valid": False, "errors": [
        {"node_id": "1", "field": "images", "code": "autogrow_no_slots"},
    ]}
    seen = {}

    def validate(args, timeout):
        seen["args"] = args
        schema_path = Path(args[args.index("--input") + 1])
        seen["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        return {"data": validation}

    monkeypatch.setattr(provider, "_run", validate)
    graph_path = tmp_path / "qwen-validation-test.json"
    graph = {"1": {"class_type": "TextEncodeQwenImage21", "inputs": {"prompt": "a landscape"}}}
    try:
        result = provider.validate_api_graph(graph_path, graph)
    finally:
        graph_path.with_suffix(".object-info.json").unlink(missing_ok=True)

    assert result["valid"] is True
    assert result["errors"] == []
    assert seen["args"][0] == "--json"
    assert seen["schema"]["TextEncodeQwenImage21"]["api_node"] is False


def test_video_graph_validation_uses_schema_snapshot_instead_of_live_cli_crawl(tmp_path, monkeypatch):
    settings = SimpleNamespace(comfyui_base_url="http://127.0.0.1:8188", comfy_mcp_command="comfy",
                               comfy_mcp_args=())
    provider = ComfyMcpProvider(settings)
    graph = {"1": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"prompt": "dog running"}}}
    graph_path = tmp_path / "h3.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    monkeypatch.setattr(provider, "live_node_schemas", lambda value: {
        "MiniMaxH3ReferenceToVideo": {"input": {"required": {}}}
    })
    seen = {}

    def validate(args, timeout):
        seen["args"] = args
        schema_path = Path(args[args.index("--input") + 1])
        seen["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        return {"data": {"valid": True, "errors": []}}

    monkeypatch.setattr(provider, "_run", validate)

    assert provider.validate_api_graph(graph_path, graph) == {"valid": True, "errors": []}
    assert "--input" in seen["args"]
    assert "MiniMaxH3ReferenceToVideo" in seen["schema"]
