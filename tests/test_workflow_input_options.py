import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from darius_api.main import create_app
from darius_api.providers import ComfyMcpProvider, ProviderError
from test_media_backend import settings_for


def test_installed_options_follow_graph_slots_and_offline_is_recoverable(tmp_path, monkeypatch):
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"node.with.dots": {"class_type": "Loader", "inputs": {"lora_name": "old.safetensors", "strength": 1, "aspect_ratio": "1:1"}}}))
    contract = SimpleNamespace(execution_provider="local-comfyui", runtime_mapping=SimpleNamespace(api_format=True), workflow_reference=str(graph), required_inputs=[
        SimpleNamespace(key="input_0", maps_to=SimpleNamespace(slot="node.with.dots.lora_name")),
        SimpleNamespace(key="input_1", maps_to=SimpleNamespace(slot="node.with.dots.strength")),
        SimpleNamespace(key="input_2", maps_to=SimpleNamespace(slot="node.with.dots.aspect_ratio")),
    ])
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.registry, "get", lambda _: contract)
        monkeypatch.setattr(ComfyMcpProvider, "live_node_schemas", lambda *_: {"Loader": {"input": {"required": {"lora_name": [["None", "portrait.safetensors"]], "strength": ["FLOAT", {"min": 0}], "aspect_ratio": ["COMBO", {"options": ["1:1", "16:9"]}]}}}})
        response = client.get("/api/v1/workflows/test/input-options")
        assert response.status_code == 200
        assert response.json() == {"input_0": ["None", "portrait.safetensors"], "input_2": ["1:1", "16:9"]}
        def offline(*a, **k):
            raise ProviderError("offline")
        monkeypatch.setattr(ComfyMcpProvider, "live_node_schemas", offline)
        assert client.get("/api/v1/workflows/test/input-options").status_code == 503
