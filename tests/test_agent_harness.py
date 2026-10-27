import json

import pytest

from darius_api.agent_harness import parse_assistant_answer, run_assistant_graph
from darius_api.providers import ProviderError
from test_media_backend import settings_for


def final():
    return {"id": "response-final", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"reply": "Render queued", "generation_prompt": None, "workflow_id": None})}]}]}


def call(operation, call_id="call-1"):
    return {"type": "function_call", "name": "comfyui", "call_id": call_id,
            "arguments": json.dumps({"operation": operation, "arguments_json": "{}"})}


def request():
    return {"model": "test", "input": [{"role": "user", "content": "animate the selected image"}]}


def test_identical_failed_tool_is_not_executed_again_but_alternative_can_continue(tmp_path):
    operations = []
    replies = iter([{"output": [call("inspect_workflow", "a")]},
                    {"output": [call("inspect_workflow", "b")]},
                    {"output": [call("discover_workflows", "c")]}, final()])
    def tool(args, timeout):
        operations.append(args["operation"])
        return {"error": "Unsupported graph"} if args["operation"] == "inspect_workflow" else {"workflows": []}
    result = run_assistant_graph(settings_for(tmp_path), request(), "guard", "project", lambda *args, **kwargs: next(replies), tool)
    assert operations == ["inspect_workflow", "discover_workflows"]
    assert [item["ok"] for item in result["tool_activity"]] == [False, False, True]


@pytest.mark.parametrize('text', ['What happens when you run shot 5?', 'Why generate shot 5?',
                                 'Explain whether to render this image'])
def test_informational_render_questions_do_not_trigger_fallback(text):
    from darius_api.local_render import requests_render
    assert not requests_render(text)


def test_parser_accepts_fenced_and_compatible_output_text():
    assert parse_assistant_answer([{"type": "message", "content": [{"type": "output_text", "text": "```json\n{\"reply\":\"Ready\",\"generation_prompt\":null,\"workflow_id\":null}\n```"}]}])["reply"] == "Ready"
    assert parse_assistant_answer([{"type": "output_text", "text": "{\"reply\":\"Ready\",\"generation_prompt\":null,\"workflow_id\":null}"}])["reply"] == "Ready"


def test_explicit_resume_allows_retry_of_transient_tool_failure(tmp_path):
    settings = settings_for(tmp_path)
    operations = []
    responses = iter([{"output": [call("inspect_workflow")]}, ProviderError("offline")])
    def model(body, timeout):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response
    def tool(args, timeout):
        operations.append(args["operation"])
        return {"error": "temporary outage"} if len(operations) == 1 else {"ok": True}
    with pytest.raises(ProviderError):
        run_assistant_graph(settings, request(), "retry-tool", "project", model, tool)
    responses = iter([{"output": [call("inspect_workflow", "retry")]}, final()])
    run_assistant_graph(settings, request(), "retry-tool", "project", model, tool)
    assert operations == ["inspect_workflow", "inspect_workflow"]


def test_resumes_after_model_failure_without_repeating_saved_queue(tmp_path):
    settings = settings_for(tmp_path)
    operations = []
    replies = iter([{"output": [call("queue_local_render")]}, ProviderError("temporary outage")])

    def model(body, timeout):
        result = next(replies)
        if isinstance(result, Exception):
            raise result
        return result

    def tool(args, timeout):
        operations.append(args["operation"])
        return {"job_id": "job-1", "status": "queued"}

    with pytest.raises(ProviderError, match="temporary outage"):
        run_assistant_graph(settings, request(), "message-1", "project-1", model, tool)
    received = []

    def resumed_model(body, timeout):
        received.append(body)
        return final()

    result = run_assistant_graph(settings, request(), "message-1", "project-1", resumed_model, tool)
    assert operations == ["queue_local_render"]
    assert any(item.get("type") == "function_call_output" for item in received[0]["input"])
    assert result["tool_activity"] == [{"operation": "queue_local_render", "ok": True}]
    # A response lost on its way to the UI can be retrieved without calling the model again.
    assert run_assistant_graph(settings, request(), "message-1", "project-1", lambda *_: pytest.fail("replayed model"), tool) == result


def test_checkpoints_are_project_scoped(tmp_path):
    settings = settings_for(tmp_path)
    calls = []

    def model(body, timeout):
        calls.append(body)
        return final()

    for project in ["a", "b", "a"]:
        run_assistant_graph(settings, request(), "same-message-id", project, model, None)
    assert len(calls) == 2


def test_auto_render_does_not_use_a_workflow_from_old_chat(tmp_path, monkeypatch):
    from types import SimpleNamespace
    settings = settings_for(tmp_path)
    monkeypatch.setattr('darius_api.agent_harness.verify_project_result', lambda *a: {'state': 'replied'})
    class Bridge:
        registry = SimpleNamespace(enabled=lambda: [SimpleNamespace(id='assistant-old')])
        def call(self, *args):
            pytest.fail('No tool was requested')
        def finish_auto_render(self, workflow_id):
            pytest.fail('A workflow from old chat must not automatically run')
    output = [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({
        'reply': 'Here is an old draft', 'generation_prompt': 'test', 'workflow_id': 'assistant-old'})}]}]
    result = run_assistant_graph(settings, request(), 'old-draft', 'p',
                                 lambda *a, **k: {'output': output}, Bridge().call)
    assert result['task']['state'] == 'draft'


def test_explicit_review_draft_never_triggers_auto_render_fallback(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from darius_api.workflow_executor import final_response
    monkeypatch.setattr("darius_api.agent_harness.verify_project_result", lambda *a: {"state": "replied"})
    operations = []
    class Bridge:
        registry = SimpleNamespace(enabled=lambda: [SimpleNamespace(id="assistant-camera")])
        def call(self, args, timeout):
            operations.append(args["operation"])
            return {"workflow_id": "assistant-camera"}
        def finish_auto_render(self, workflow_id):
            pytest.fail("A custom recipe awaiting explicit approval must not be automatically queued")
    replies = iter([{"output": [call("prepare_workflow")]},
        final_response("Validated video draft ready for Review generation; no render was submitted.",
            prompt="An angel unfurling her wings.", workflow_id="assistant-camera", state="awaiting_approval")])
    result = run_assistant_graph(settings_for(tmp_path), request(), "review-video", "project",
        lambda *a, **k: next(replies), Bridge().call)
    assert operations == ["prepare_workflow"]
    assert result["task"]["state"] == "awaiting_approval"
    assert parse_assistant_answer(result["output"])["workflow_execution"]["state"] == "awaiting_approval"


def test_each_tool_is_checkpointed_separately(tmp_path):
    settings = settings_for(tmp_path)
    tools = []

    def tool(args, timeout):
        tools.append(args["operation"])
        if args["operation"] == "view_assets" and tools.count("view_assets") == 1:
            raise RuntimeError("process interrupted")
        return {"ok": True}

    with pytest.raises(ProviderError, match="internal RuntimeError"):
        run_assistant_graph(settings, request(), "m", "p", lambda *a, **k: {"output": [call("list_assets"), call("view_assets", "call-2")]}, tool)
    run_assistant_graph(settings, request(), "m", "p", lambda *a, **k: final(), tool)
    assert tools == ["list_assets", "view_assets", "view_assets"]


def test_verified_presentation_receipt_survives_checkpoint_retry(tmp_path):
    settings = settings_for(tmp_path)
    receipt = {"id": "receipt", "action": "open", "asset_ids": ["image"], "project_id": "project"}
    calls = []
    def tool(args, timeout):
        calls.append(args["operation"])
        return {"presentation_action": receipt}
    count = 0
    def model(body, timeout):
        nonlocal count
        count += 1
        if count == 1: return {"output": [call("present_assets")]}
        raise ProviderError("temporary model outage")
    with pytest.raises(ProviderError):
        run_assistant_graph(settings, request(), "present", "project", model, tool)
    result = run_assistant_graph(settings, request(), "present", "project", lambda *a, **k: final(), tool)
    assert calls == ["present_assets"]
    assert result["presentation_actions"] == [receipt]


def test_repeated_tool_errors_force_a_final_reply(tmp_path):
    settings = settings_for(tmp_path)
    calls = []
    outputs = iter([call("create_shot"), call("create_shot"), final()["output"][0]])
    def model(body, timeout):
        calls.append(body)
        return {"output": [next(outputs)]}
    def tool(args, timeout):
        return {"error": "shot conflicts with an existing record"}
    result = run_assistant_graph(settings, request(), "repeat", "project", model, tool)
    assert result["output"] == final()["output"]
    assert len(calls) == 3


def test_invalid_final_reply_can_be_retried(tmp_path):
    settings = settings_for(tmp_path)
    with pytest.raises(ProviderError, match="final reply was incomplete"):
        run_assistant_graph(settings, request(), "m", "p", lambda *a, **k: {"output": []}, None)
    assert run_assistant_graph(settings, request(), "m", "p", lambda *a, **k: final(), None)["task"]["state"] == "replied"


def test_deepseek_repairs_nearly_valid_final_reply(tmp_path):
    settings = settings_for(tmp_path)
    replies = iter([{"output": [{"type": "message", "content": [{"type": "output_text", "text": "not json"}]}]}, final()])
    result = run_assistant_graph(settings, request(), "repair", "p", lambda *a, **k: next(replies), None, provider_name="deepseek")
    assert result["task"]["state"] == "replied"


def test_event_stream_resumes_beyond_first_500_events(tmp_path):
    from fastapi.testclient import TestClient
    from darius_api.main import create_app
    from darius_api.services import add_event
    from test_media_backend import create_project
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        project = create_project(client)
        with app.state.session_factory.begin() as session:
            for index in range(505):
                add_event(session, project, "assistant.tool_activity", "message", "test", {"step": index})
        url = f"/api/v1/events/stream?project_id={project}&once=true"
        first = client.get(url).text
        ids = [line[4:] for line in first.splitlines() if line.startswith("id: ")]
        assert len(ids) == 500
        resumed = client.get(url, headers={"Last-Event-ID": ids[-1]}).text
        next_ids = [line[4:] for line in resumed.splitlines() if line.startswith("id: ")]
        assert len(next_ids) == 6
        assert not set(ids).intersection(next_ids)
