import json
import shutil
import pytest
from dataclasses import replace

from fastapi.testclient import TestClient

from darius_api.comfy_assistant import ComfyAssistantTools, TOOL_DEFINITIONS
from darius_api.main import create_app
from darius_api.providers import ComfyMcpProvider, OpenAIPlannerProvider
from darius_api.services import create_action_plan, approve_action_plan
from darius_api.workflows import WorkflowRegistry, resolve_graph_slot
from test_media_backend import settings_for, create_project


GRAPH = {"1": {"class_type": "EmptyImage", "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": 0}},
         "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "original"}}}


def test_expensive_workflow_tools_receive_video_sized_timeout(tmp_path, monkeypatch):
    tools = ComfyAssistantTools(settings_for(tmp_path), None, None)
    observed = []
    monkeypatch.setattr(tools, "_call", lambda operation, args, timeout: observed.append((operation, timeout)) or {})

    tools.call({"operation": "prepare_graph", "arguments": {"graph": GRAPH, "name": "Test"}}, timeout=180)
    tools.call({"operation": "list_workflows", "arguments": {}}, timeout=180)

    assert observed == [("prepare_graph", 120), ("list_workflows", 25)]


def test_slot_resolution_preserves_literal_dotted_fields_and_node_ids():
    graph = {"30:16": {"inputs": {"sampling_mode.temperature": 0.7}}, "node.with.dots": {"inputs": {"field.with.dots": 1}}}
    assert resolve_graph_slot(graph, "30:16.sampling_mode.temperature") == ("30:16", "sampling_mode.temperature")
    assert resolve_graph_slot(graph, "node.with.dots.field.with.dots") == ("node.with.dots", "field.with.dots")
    with pytest.raises(ValueError, match="unknown"):
        resolve_graph_slot(graph, "30:16.missing")
    graph["30:16.sampling_mode"] = {"inputs": {"temperature": 0.8}}
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_graph_slot(graph, "30:16.sampling_mode.temperature")


def test_prepare_and_execute_workflow_with_dotted_input_name(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    definitions = tmp_path / "definitions"
    shutil.copytree(settings.workflow_definitions_dir, definitions)
    settings = replace(settings, workflow_definitions_dir=definitions)
    graph = {**GRAPH, "30:16": {"class_type": "TextGenerate", "inputs": {"sampling_mode.temperature": 0.7}}}
    monkeypatch.setattr(ComfyMcpProvider, "_run", lambda *_, **__: {"data": {"valid": True, "prompt_id": "test"}})
    app = create_app(settings)
    with TestClient(app) as client:
        project = create_project(client)
        bridge = ComfyAssistantTools(settings, app.state.registry, app.state.session_factory)
        original = bridge.call({"operation": "prepare_graph", "arguments_json": json.dumps({"graph": graph, "name": "Dotted field"})})
        edited = bridge.call({"operation": "prepare_workflow", "arguments_json": json.dumps({"workflow_id": original["workflow_id"], "name": "Edited dotted field", "overrides": {"30:16.sampling_mode.temperature": 0.9}})})
        assert "error" not in edited, edited
        contract = app.state.registry.get(edited["workflow_id"])
        provider = ComfyMcpProvider(settings)
        monkeypatch.setattr(provider, "_submit_verified_local_graph",
                            lambda *_: {"data": {"prompt_id": "test"}})
        monkeypatch.setattr(provider, "_history", lambda *_: {"status": {"completed": True}})
        monkeypatch.setattr(provider, "_collect", lambda *_: ())
        provider.execute(contract, contract.validate_inputs({}), project, "dotted-input")
        saved = json.loads((settings.data_dir / "jobs/dotted-input/workflow.json").read_text())
        assert saved["30:16"]["inputs"]["sampling_mode.temperature"] == 0.9
        from pathlib import Path
        original_graph = json.loads(Path(app.state.registry.get(original["workflow_id"]).workflow_reference).read_text())
        assert original_graph["30:16"]["inputs"]["sampling_mode.temperature"] == 0.7


@pytest.mark.parametrize("node", [None, [], {"class_type": "SaveImage", "inputs": []}, {"inputs": {}}])
def test_malformed_graph_nodes_are_rejected_before_comfy_call(tmp_path, monkeypatch, node):
    def unexpected(*args, **kwargs):
        pytest.fail("Malformed graph must not reach ComfyUI")

    monkeypatch.setattr(ComfyMcpProvider, "_run", unexpected)
    tools = ComfyAssistantTools(settings_for(tmp_path), None, None)
    result = tools.call({"operation": "prepare_graph", "arguments_json": json.dumps({"graph": {"1": node}, "name": "Invalid"})})
    assert "error" in result


@pytest.mark.parametrize("validation", [{}, {"valid": None}, {"valid": "true"}])
def test_draft_requires_positive_validation(tmp_path, monkeypatch, validation):
    monkeypatch.setattr(ComfyMcpProvider, "_run", lambda *_, **__: {"data": validation})
    tools = ComfyAssistantTools(settings_for(tmp_path), None, None)
    result = tools.call({"operation": "prepare_graph", "arguments_json": json.dumps({"graph": GRAPH, "name": "Unverified"})})
    assert result["error"] == "Workflow validation failed"


def test_graph_draft_survives_worker_restart_and_requires_approval(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    definitions = tmp_path / "definitions"
    shutil.copytree(settings.workflow_definitions_dir, definitions)
    settings = replace(settings, workflow_definitions_dir=definitions)
    calls = []

    def command(self, args, timeout):
        calls.append(args)
        return {"data": {"valid": True}}

    monkeypatch.setattr(ComfyMcpProvider, "_run", command)
    app = create_app(settings)
    with TestClient(app) as client:
        project_id = create_project(client)
        worker_registry = WorkflowRegistry(definitions)
        worker_registry.load()
        tools = ComfyAssistantTools(settings, app.state.registry, app.state.session_factory, project_id=project_id)
        prepared = tools.call({"operation": "prepare_graph", "arguments_json": json.dumps({"graph": GRAPH, "name": "A new composition", "output_kind": "image"})})
        assert "error" not in prepared, prepared
        contract = worker_registry.get(prepared["workflow_id"])
        assert contract.runtime_mapping.api_format
        assert client.get(f"/api/v1/jobs?project_id={project_id}").json() == []
        assert all("--wait" not in args for args in calls)
        inputs = contract.validate_inputs({})
        plan = create_action_plan(app.state.session_factory, app.state.registry, project_id, contract.id, "Make a still", inputs)
        assert plan.state == "proposed"
        assert client.get(f"/api/v1/jobs?project_id={project_id}").json() == []
        approved = approve_action_plan(app.state.session_factory, app.state.registry, plan.id)
        assert approved.job_id
        assert len(client.get(f"/api/v1/jobs?project_id={project_id}").json()) == 1


def test_tools_reject_traversal_and_invalid_graphs_without_registering(tmp_path, monkeypatch):
    tools = ComfyAssistantTools(settings_for(tmp_path), None, None)
    assert "error" in tools.call({"operation": "inspect_workflow", "arguments_json": '{"workflow_id":"../secret.json"}'})
    assert "error" in tools.call({"operation": "prepare_graph", "arguments_json": '{"graph":{}}'})
    monkeypatch.setattr(ComfyMcpProvider, "_run", lambda *_, **__: {"data": {"valid": False, "errors": ["Missing node"]}})
    result = tools.call({"operation": "prepare_graph", "arguments_json": json.dumps({"graph": GRAPH, "name": "Bad draft"})})
    assert result["error"] == "Workflow validation failed"


def test_draft_rejects_unbound_saved_example_images(tmp_path, monkeypatch):
    monkeypatch.setattr(ComfyMcpProvider, "validate_api_graph", lambda *args, **kwargs: {
        "valid": True, "errors": [],
    })
    graph = {
        **GRAPH,
        "7": {"class_type": "LoadImage", "inputs": {"image": "some-other-project.png"}},
    }
    tools = ComfyAssistantTools(settings_for(tmp_path), None, None)

    result = tools.call({"operation": "prepare_graph", "arguments": {
        # A previous upload must not authorize this unrelated saved filename.
        "graph": graph, "name": "Unsafe template",
    }})

    assert "Unbound template image inputs" in result["error"]
    assert "Saved example images cannot enter a project draft" in result["error"]
    tools.source_asset_ids = ["earlier-upload"]
    again = tools.call({"operation": "prepare_graph", "arguments": {"graph": graph, "name": "Still unsafe"}})
    assert "Unbound template image inputs" in again["error"]


def test_responses_tool_loop_uses_live_result_and_preserves_reasoning(tmp_path, monkeypatch):
    provider = OpenAIPlannerProvider(replace(settings_for(tmp_path), openai_api_key="test", openai_planner_model="test"))
    round_number = 0

    def response(body, timeout):
        nonlocal round_number
        round_number += 1
        if round_number == 1:
            assert body["tools"] == TOOL_DEFINITIONS
            return {"output": [{"type": "reasoning", "id": "reasoning-1", "summary": []}, {"type": "function_call", "call_id": "call-1", "name": "comfyui", "arguments": '{"operation":"list_workflows","arguments_json":"{}"}'}]}
        assert body["input"][-3]["type"] == "reasoning"
        assert json.loads(body["input"][-1]["output"])["workflows"][0]["id"] == "unregistered.json"
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"reply": "I found unregistered.json in your live ComfyUI.", "generation_prompt": None, "workflow_id": None})}]}]}

    monkeypatch.setattr(provider, "_responses", response)
    # Explanations need a final model turn; plain listings use the verified receipt directly.
    result = provider.plan({"assistant_conversation": True}, "Explain live workflows", tool_runner=lambda *_: {"workflows": [{"id": "unregistered.json"}]}, tool_definitions=TOOL_DEFINITIONS)
    assert round_number == 2
    assert result["tool_activity"] == [{"operation": "list_workflows", "ok": True}]


def test_api_graph_execution_preserves_original_and_sets_output_prefixes(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    definitions = tmp_path / "definitions"
    shutil.copytree(settings.workflow_definitions_dir, definitions)
    settings = replace(settings, workflow_definitions_dir=definitions)
    app = create_app(settings)
    monkeypatch.setattr(ComfyMcpProvider, "_run", lambda *_, **__: {"data": {"valid": True, "prompt_id": "test-prompt"}})
    with TestClient(app) as client:
        project = create_project(client)
        bridge = ComfyAssistantTools(settings, app.state.registry, app.state.session_factory)
        prepared = bridge.call({"operation": "prepare_graph", "arguments_json": json.dumps({"graph": GRAPH, "name": "A composition"})})
        contract = app.state.registry.get(prepared["workflow_id"])
        provider = ComfyMcpProvider(settings)
        monkeypatch.setattr(provider, "_submit_verified_local_graph",
                            lambda *_: {"data": {"prompt_id": "test-prompt"}})
        monkeypatch.setattr(provider, "_history", lambda *_: {"status": {"completed": True}})
        monkeypatch.setattr(provider, "_collect", lambda *_: ())
        provider.execute(contract, contract.validate_inputs({}), project, "job-test")
        copied = json.loads((settings.data_dir / "jobs/job-test/workflow.json").read_text())
        assert copied["2"]["inputs"]["filename_prefix"] == f"darius/{project}/job-test/a-composition-job-test-01/2"
        assert copied["1"] == GRAPH["1"]
        from pathlib import Path
        assert json.loads(Path(contract.workflow_reference).read_text()) == GRAPH
