import json

from fastapi.testclient import TestClient

from darius_api.comfy_assistant import ComfyAssistantTools
from darius_api.main import create_app
from test_media_backend import create_project, settings_for
from darius_api.agent_harness import run_assistant_graph
import pytest


def call(bridge, operation, **args):
    return bridge.call({"operation": operation, "arguments_json": json.dumps(args)})


@pytest.mark.parametrize("provider", ["openai", "deepseek"])
def test_real_character_result_survives_checkpoint_and_model_turn(tmp_path, provider):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        project = create_project(client)
        bridge = ComfyAssistantTools(app.state.settings, app.state.registry, app.state.session_factory, project_id=project)
        requests = []
        def model(body, timeout):
            requests.append(body)
            if len(requests) == 1:
                return {"output": [{"type": "function_call", "name": "comfyui", "call_id": "create", "arguments": json.dumps({"operation": "create_character", "arguments_json": json.dumps({"name": "Zoorglob"})})}]}
            result = json.loads(body["input"][-1]["output"])
            assert isinstance(result["record"]["created_at"], str)
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"reply": "Zoorglob is saved.", "generation_prompt": None, "workflow_id": None})}]}]}
        result = run_assistant_graph(app.state.settings, {"input": []}, "serialization", project, model, bridge.call, provider_name=provider)
        assert result["tool_activity"] == [{"operation": "create_character", "ok": True}]
        assert run_assistant_graph(app.state.settings, {"input": []}, "serialization", project, lambda *a, **k: pytest.fail("replayed"), bridge.call, provider_name=provider) == result


def test_chat_story_tools_create_project_scoped_character_scene_and_shot(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        project_id = create_project(client)
        bridge = ComfyAssistantTools(app.state.settings, app.state.registry, app.state.session_factory, project_id=project_id)
        character = call(bridge, "create_character", name="Mara", description="A careful courier", canonical_prompt="Mara, charcoal coat")
        assert character["record"]["name"] == "Mara"
        scene = call(bridge, "create_scene", number=1, title="The platform", location="Station", status="draft")
        assert scene["record"]["project_id"] == project_id
        shot = call(bridge, "create_shot", scene_id=scene["record"]["id"], number=1, description="Mara waits", shot_type="Wide", duration_target=4)
        assert shot["record"]["scene_id"] == scene["record"]["id"]
        next_shot = call(bridge, "create_shot", scene_id=scene["record"]["id"], number=1, description="Mara close-up", shot_type="Close", duration_target=3)
        assert next_shot["record"]["number"] == 2
        same_character = call(bridge, "create_character", name="Mara", description="Changed wording")
        assert same_character["record"]["id"] == character["record"]["id"]
        updated = call(bridge, "update_scene", scene_id=scene["record"]["id"], mood="Rainy")
        assert updated["record"]["mood"] == "Rainy"
        listed = client.get(f"/api/v1/projects/{project_id}/scenes").json()
        assert listed[0]["title"] == "The platform"


def test_story_tools_reject_cross_project_scene(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        first, second = create_project(client, "One"), create_project(client, "Two")
        scene = client.post(f"/api/v1/projects/{first}/scenes", json={"number": 1, "title": "Private"}).json()
        bridge = ComfyAssistantTools(app.state.settings, app.state.registry, app.state.session_factory, project_id=second)
        result = call(bridge, "create_shot", scene_id=scene["id"], number=1)
        assert "does not belong" in result["error"]


def test_prepare_graph_rejects_unbound_template_images(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        project_id = create_project(client)
        bridge = ComfyAssistantTools(app.state.settings, app.state.registry, app.state.session_factory, project_id=project_id)
        result = call(bridge, "prepare_graph", graph={"1": {"class_type": "LoadImage", "inputs": {"image": "__REFERENCE__"}}, "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "test"}}}, name="bad template")
        assert "Unbound template image inputs" in result["error"]
