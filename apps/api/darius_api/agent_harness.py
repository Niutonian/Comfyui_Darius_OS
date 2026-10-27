"""Checkpointed assistant execution. Project records and render workers remain authoritative."""
from __future__ import annotations

import hashlib
import json
import re
import time
import traceback
from copy import deepcopy
from typing import Any, TypedDict
from fastapi.encoders import jsonable_encoder

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .providers import ProviderError
from .task_control import TaskStopped, check_task_control


class TaskState(TypedDict, total=False):
    request: dict
    output: list
    pending: list
    trace: list
    rounds: int
    calls: int
    response_id: str | None
    viewed_asset_ids: list[str]
    source_asset_ids: list[str]
    result: dict
    answer: dict
    prepared_workflow_id: str | None
    failed_requests: list[str]
    continue_generation: bool
    presentation_actions: list[dict]


def output_text(output: list[dict]) -> str:
    """Collect text across Responses API and OpenAI-compatible message shapes."""
    parts: list[str] = []
    for item in output:
        if item.get("type") not in {"message", "output_text"}:
            continue
        content = item.get("content", item.get("text", ""))
        if isinstance(content, str):
            parts.append(content)
            continue
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
    return "".join(parts).strip()


def parse_assistant_answer(output: list[dict]) -> dict[str, Any]:
    """Parse strict JSON while tolerating fenced/compatible provider output."""
    text = output_text(output)
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            answer = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(answer, dict) and isinstance(answer.get("reply"), str) and answer["reply"].strip():
            return answer
    raise ValueError("empty or malformed assistant reply")


def run_assistant_graph(
    settings, body_request, task_id, project_id, model_call, tool_runner, *, provider_name="openai"
):
    """Resume one message's model/tool sequence; never checkpoint live clients or credentials.

    A failed in-flight tool may run again on recovery. The render queue's persisted
    message association is the duplicate-job guard, not the checkpoint alone.
    """
    # Reasoning models, especially with inspected image context, can legitimately
    # need more than one minute for a single response.
    deadline = time.monotonic() + 300
    bridge = getattr(tool_runner, "__self__", None)
    task_key = f"{project_id}:{task_id}"
    from .providers import OpenAIPlannerProvider
    _, initial_context = OpenAIPlannerProvider._original_request(body_request)
    revision = initial_context.get("task_revision", 0)
    if isinstance(revision, int) and revision > 0:
        task_key += f":preparation-{revision}"
    executor_active = (initial_context.get("preferred_workflow") or {}).get("execution_provider") == "local-comfyui" and bool(initial_context.get("workflow_route"))
    round_limit = 16 if executor_active else 12
    from .media_intent import is_information_request
    original_text, _ = OpenAIPlannerProvider._original_request(body_request)
    informational = is_information_request(original_text)

    def validate_answer(output):
        answer = parse_assistant_answer(output)
        if informational:
            # A listing/explanation cannot become a generation proposal just
            # because a provider echoed a workflow name or sample prompt.
            answer = {**answer, "generation_prompt": None, "workflow_id": None}
        prompt = answer.get("generation_prompt")
        if prompt is not None and (not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000):
            raise ValueError("invalid generation prompt")
        if prompt and bridge and answer.get("workflow_id") not in {w.id for w in bridge.registry.enabled()}:
            raise ValueError("unknown workflow")
        return answer

    def activity(step, state="running"):
        if bridge and hasattr(bridge, "on_activity"):
            bridge.on_activity(step, state)

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 1:
            raise ProviderError("Task paused at its time limit. Retry to resume the saved steps.")
        return seconds

    def model(state: TaskState):
        check_task_control(bridge)
        activity("planning_reply")
        request = deepcopy(state["request"])
        # Give the model a final response turn after the exploration budget.
        # Individual workflow inspections can fail because a saved ComfyUI
        # graph uses an unavailable/custom node. That is a candidate-level
        # failure, not a reason to abandon discovery of the remaining defaults.
        # Keep the hard call/round/time budgets as the loop guard instead.
        if state["calls"] >= 16 or state["rounds"] >= round_limit - 1:
            request["tool_choice"] = "none"
        response = model_call(request, timeout=min(180, remaining()))
        output = response.get("output", [])
        pending = [item for item in output if item.get("type") == "function_call"]
        if pending and (state["calls"] >= 16 or state["rounds"] >= round_limit):
            raise ProviderError("Task reached its tool budget. Start a more focused request.")
        answer: dict[str, Any] = {}
        if not pending:
            # DeepSeek occasionally emits a nearly-correct final turn after a
            # long tool chain. Give it one cheap repair turn before surfacing
            # an interruption to the user.
            try:
                answer = validate_answer(output)
            except (ValueError, TypeError) as exc:
                if provider_name not in {"deepseek", "ollama"}:
                    raise ProviderError("The final reply was incomplete. Retry to resume the saved task.") from exc
                else:
                    repair = deepcopy(request)
                    repair["tool_choice"] = "none"
                    if provider_name == "ollama":
                        from .diagnostics import record
                        record(settings, provider_name, "warning", "final_reply_format_repair", reason=str(exc), task_id=task_id)
                        repair.pop("tools", None)
                        repair["stream"] = False
                        repair["text"] = {"format": {"type": "json_schema", "name": "darius_reply", "strict": True,
                            "schema": {"type": "object", "additionalProperties": False, "properties": {
                                "reply": {"type": "string"}, "generation_prompt": {"type": ["string", "null"]},
                                "workflow_id": {"type": ["string", "null"]}},
                                "required": ["reply", "generation_prompt", "workflow_id"]}}}
                    repair["input"].append({
                        "role": "user",
                        "content": "Format the final reply only: return a valid JSON object with reply, generation_prompt, and workflow_id. Do not use Markdown or commentary. Tools are unavailable: do not repeat any action or invent execution status. Use the already-confirmed tool results; for informational replies set generation_prompt and workflow_id to null.",
                    })
                    response = model_call(repair, timeout=min(90, remaining()))
                    output = response.get("output", [])
                    pending = [item for item in output if item.get("type") == "function_call"]
                    if pending:
                        raise ProviderError("The final reply was incomplete. Retry to resume the saved task.")
                    else:
                        try:
                            answer = validate_answer(output)
                        except (ValueError, TypeError):
                            raise ProviderError("The final reply was incomplete. Retry to resume the saved task.")
                    request = repair
            if informational:
                output = [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer, ensure_ascii=False)}]}]
            if not answer:
                answer = {"reply": "I completed the requested operation, but the final response was incomplete. Ask me to continue.", "generation_prompt": None, "workflow_id": None}
            try:
                parse_assistant_answer(output)
            except ValueError:
                output = [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}]
        request["input"].extend(output)
        return {"request": request, "output": output, "answer": answer if not pending else {}, "pending": pending, "continue_generation": False,
                "rounds": state["rounds"] + 1, "response_id": response.get("id")}

    def tool(state: TaskState):
        check_task_control(bridge)
        if not tool_runner:
            raise ProviderError("The assistant requested an unavailable tool")
        if state["calls"] >= 16:
            raise ProviderError("Task reached its tool budget. Start a more focused request.")
        if bridge:
            bridge.viewed_asset_ids = list(state.get("viewed_asset_ids", []))
            bridge.source_asset_ids = list(state.get("source_asset_ids", []))
        item = state["pending"][0]
        arguments: dict[str, Any] = {}
        failed_requests = list(state.get("failed_requests", []))
        fingerprint = None
        try:
            arguments = json.loads(item["arguments"])
            if not isinstance(arguments, dict) or item["name"] != "comfyui":
                raise ValueError("Invalid tool request")
            fingerprint = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()
            if fingerprint in failed_requests:
                result = {"error": "This identical tool request already failed. Correct its arguments, use a different supported approach, or explain the blocker. Do not repeat it."}
            else:
                result = tool_runner(arguments, max(1, int(remaining())))
        except TaskStopped:
            raise
        except (ValueError, KeyError, TypeError, ProviderError) as exc:
            result = {"error": str(exc)}
        result = jsonable_encoder(dict(result))
        if "error" in result:
            from .workflow_errors import failure_details
            result = {**failure_details(result["error"]), **result}
        if "error" in result and fingerprint and fingerprint not in failed_requests:
            failed_requests.append(fingerprint)
        images = result.pop("_image_content", None)
        request = deepcopy(state["request"])
        request["input"].append({"type": "function_call_output", "call_id": item["call_id"], "output": json.dumps(result, ensure_ascii=False)})
        if images:
            request["input"].append({"role": "user", "content": images})
        operation = arguments.get("operation", "unknown") if isinstance(arguments, dict) else "unknown"
        trace = [*state["trace"], {"operation": operation, "ok": "error" not in result,
                 **({key: result[key] for key in ("error", "error_code", "recovery", "retryable") if key in result} if "error" in result else {})}]
        prepared = state.get("prepared_workflow_id")
        if operation in {"prepare_workflow", "prepare_graph"}:
            prepared = result.get("workflow_id") if "error" not in result else None
        return {"request": request, "pending": state["pending"][1:], "trace": trace,
                "presentation_actions": [*state.get("presentation_actions", []), *([result["presentation_action"]] if operation == "present_assets" and "error" not in result and isinstance(result.get("presentation_action"), dict) else [])][-8:],
                "failed_requests": failed_requests,
                "prepared_workflow_id": prepared,
                "calls": state["calls"] + 1,
                "viewed_asset_ids": list(getattr(bridge, "viewed_asset_ids", [])),
                "source_asset_ids": list(getattr(bridge, "source_asset_ids", []))}

    def verify(state: TaskState):
        check_task_control(bridge)
        activity("verifying_result")
        outcome = verify_project_result(bridge, project_id, task_id) if bridge else {"state": "replied"}
        answer = state.get("answer") or parse_assistant_answer(state["output"])
        output = state["output"]
        trace = state["trace"]
        prepared = state.get("prepared_workflow_id")
        execution = answer.get("workflow_execution") or {}
        if execution.get("state") in {"blocked", "needs_input"}:
            activity("workflow_blocked", "failed")
            return {"continue_generation": False, "result": {
                "provider": provider_name, "response_id": state.get("response_id"),
                "output": output, "tool_activity": trace,
                "task": {"id": task_id, "engine": "langgraph", **outcome,
                         "state": outcome["state"] if outcome.get("job_id") else execution["state"],
                         "error": answer.get("reply"), "error_code": execution.get("error_code"), "recovery": execution.get("recovery")},
                "viewed_asset_ids": state.get("viewed_asset_ids", [])}}
        from .providers import OpenAIPlannerProvider
        media_request = OpenAIPlannerProvider._is_media_request(OpenAIPlannerProvider._original_request(state["request"])[0])
        def continue_shots():
            if state["calls"] >= 16 or state["rounds"] >= 11:
                raise ProviderError("Only part of the render batch was queued. Retry to continue the remaining shot briefs; existing jobs are retained.")
            request = deepcopy(state["request"])
            request.pop("tool_choice", None)
            request["input"].append({"role": "user", "content": (
                "Execution status: the saved visual plan is only partially queued. Continue preparing and "
                "queuing its remaining brief_ids using the existing shot descriptions and references. "
                "Existing render slots are already saved; do not change their subjects or report all shots completed.")})
            return {"request": request, "continue_generation": True, "trace": trace}
        if outcome.get("job_id") and len(outcome.get("job_ids", [])) < outcome.get("requested_job_count", 1):
            # A partially queued batch must not become a finished checkpoint.
            # Reusing the same prepared graph fills only missing persisted slots.
            if not prepared:
                raise ProviderError("Only part of the render batch was queued. Retry the saved task; existing jobs are retained.")
            from .database import Message
            with bridge.session_factory() as session:
                source = session.get(Message, task_id)
                shots = (source.metadata_json.get("visual_plan") or {}).get("shots", [])
                drafts = source.metadata_json.get("shot_workflows", {})
            if len(shots) > 1:
                if any(shot["id"] not in drafts for shot in shots):
                    return continue_shots()
                queued = {}
                for shot in shots:
                    queued = tool_runner({"operation": "queue_local_render", "arguments": {"workflow_id": drafts[shot["id"]], "brief_id": shot["id"]}}, remaining())
                    if "error" in queued:
                        break
            else:
                queued = bridge.call({"operation": "queue_local_render", "arguments": {"workflow_id": prepared}}, remaining())
            if "error" in queued:
                raise ProviderError("Only part of the render batch was queued. Existing jobs are retained. " + queued["error"])
            outcome = verify_project_result(bridge, project_id, task_id)
        # Only finish a graph prepared in THIS task. Old chat workflow IDs are
        # not sufficient authority to render, and an attempted queue is not retried.
        if (outcome["state"] == "replied" and prepared
                and execution.get("state") != "awaiting_approval"
                and answer.get("workflow_id") in {None, prepared}
                and not any(item["operation"] == "queue_local_render" for item in trace)
                and bridge and hasattr(bridge, "finish_auto_render")):
            queued = bridge.finish_auto_render(prepared)
            if queued is not None:
                trace = [*trace, {"operation": "queue_local_render", "ok": "error" not in queued}]
                answer = dict(answer, workflow_id=prepared)
                if "error" in queued:
                    partial = verify_project_result(bridge, project_id, task_id)
                    if partial.get("job_id") and len(partial.get("job_ids", [])) < partial.get("requested_job_count", 1):
                        raise ProviderError("Only part of the render batch was queued. Existing jobs are retained. " + queued["error"])
                    outcome["state"] = "draft"
                    answer["reply"] = "The draft is ready, but automatic rendering could not start: " + queued["error"]
                else:
                    outcome = verify_project_result(bridge, project_id, task_id)
                    answer["reply"] = "Your render request is queued. Follow progress in Background jobs."
                output = [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}]
        if outcome.get("job_id") and len(outcome.get("job_ids", [])) < outcome.get("requested_job_count", 1):
            return continue_shots()
        reply = answer.get("reply", "")
        claimed = re.search(r"\b(?:queued|launching|rendering|generating|started|running)\b", reply, re.I)
        negated = re.search(r"\b(?:not|nothing|no|before|could|would|cannot|can't|failed)\b", reply, re.I)
        action_turn = (media_request
            or any(item.get("operation") in {"discover_workflows", "prepare_workflow", "prepare_graph", "queue_local_render"} for item in trace)
            or re.search(r"\b(?:I['’]m|I am|I have|I've|I’ve|we are|we have)\s+(?:now\s+)?(?:queued|launching|rendering|generating|started|running)\b", reply, re.I))
        if outcome.get("job_id"):
            jobs = outcome.get("jobs") or [{"job_id": outcome["job_id"], "status": outcome["state"]}]
            from .chat_labels import render_receipt
            answer = dict(answer, reply=render_receipt(jobs))
            output = [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}]
        elif bridge and action_turn and claimed and not negated:
            answer = dict(answer, reply="No render job was confirmed for this request. " + ("The workflow is a draft for review, not a running render." if prepared else "I have not started generation. Please select a compatible workflow or retry this request."))
            output = [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}]
        if outcome["state"] == "replied" and answer.get("generation_prompt"):
            outcome["state"] = "awaiting_approval" if execution.get("state") == "awaiting_approval" else "draft"
        return {"continue_generation": False, "result": {"provider": provider_name, "response_id": state.get("response_id"),
                           "presentation_actions": state.get("presentation_actions", []),
                           "output": output, "tool_activity": trace,
                           "task": {"id": task_id, "engine": "langgraph", **outcome},
                           "viewed_asset_ids": state.get("viewed_asset_ids", [])}}

    builder = StateGraph(TaskState)
    builder.add_node("model", model)
    builder.add_node("tool", tool)
    builder.add_node("verify", verify)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", lambda state: "tool" if state["pending"] else "verify")
    builder.add_conditional_edges("tool", lambda state: "tool" if state["pending"] else "model")
    builder.add_conditional_edges("verify", lambda state: "model" if state.get("continue_generation") else END)
    directory = settings.data_dir / "agent-checkpoints"
    directory.mkdir(parents=True, exist_ok=True)
    # One database per task avoids unrelated conversations contending on SQLite writes.
    filename = directory / (hashlib.sha256(task_key.encode()).hexdigest() + ".sqlite")
    with SqliteSaver.from_conn_string(str(filename)) as saver:
        graph = builder.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": task_key}, "recursion_limit": 48}
        snapshot = graph.get_state(config)
        if snapshot.values and snapshot.next:
            # An explicit user retry may recover a transient tool outage.
            resumed = deepcopy(snapshot.values["request"])
            # Keep completed tool results and the frozen brief, while honoring
            # the current model selection and current tool contracts.
            if "model" in body_request:
                resumed["model"] = body_request["model"]
            if "tools" in body_request:
                resumed["tools"] = deepcopy(body_request["tools"])
            resumed.pop("tool_choice", None)
            if resumed.get("input") and body_request.get("input") and resumed["input"][0].get("role") == body_request["input"][0].get("role") == "system":
                resumed["input"][0] = deepcopy(body_request["input"][0])
            graph.update_state(config, {"failed_requests": [], "calls": 0, "rounds": 0, "request": resumed})
        unstarted = bool(
            snapshot.values
            and snapshot.next
            and snapshot.values.get("rounds", 0) == 0
            and snapshot.values.get("calls", 0) == 0
            and not snapshot.values.get("output")
            and not snapshot.values.get("result")
        )
        # A model failure before its first completed turn leaves only the initial
        # request checkpoint. On retry, refresh that request so provider fixes and
        # prompt changes apply instead of replaying a permanently stale payload.
        initial = ({"request": body_request, "trace": [], "calls": 0, "rounds": 0,
                    "pending": [], "viewed_asset_ids": [], "source_asset_ids": []}
                   if not snapshot.values or unstarted else None)
        if snapshot.values and not snapshot.next:
            result = snapshot.values["result"]
        else:
            try:
                result = graph.invoke(initial, config, durability="sync")["result"]
            except Exception as exc:
                activity("task_paused", "failed")
                if isinstance(exc, ProviderError):
                    raise
                from .diagnostics import record
                record(settings, "backend", "error", "assistant_internal_error", project_id=project_id, task_id=task_id,
                    error_type=type(exc).__name__, detail=str(exc)[:1200],
                    frames=[{"file": frame.filename.replace("\\", "/").rsplit("/", 1)[-1],
                             "function": frame.name, "line": frame.lineno}
                            for frame in traceback.extract_tb(exc.__traceback__)[-8:]])
                raise ProviderError(f"Saved task paused because of an internal {type(exc).__name__}. Completed checkpoints are retained.") from exc
        if bridge:
            bridge.viewed_asset_ids = list(result.get("viewed_asset_ids", []))
        activity("task_" + result["task"]["state"], "failed" if result["task"]["state"] == "blocked" else "complete")
        return result


def verify_project_result(bridge, project_id, message_id):
    from pathlib import Path
    from .database import Asset, Job, Message, GenerationRecord
    from sqlalchemy import select
    from .chat_labels import job_label
    with bridge.session_factory() as session:
        message = session.get(Message, message_id)
        job_id = (message.metadata_json.get("local_render_job_id") or message.metadata_json.get("local_render_first_job_id")) if message else None
        if not job_id:
            return {"state": "replied"}
        ids = message.metadata_json.get("local_render_job_ids") or [job_id]
        jobs = []
        assets = []
        for identifier in ids:
            job = session.get(Job, identifier)
            if not job or job.project_id != project_id or job.input_payload.get("local_render_message_id") != message_id:
                raise ProviderError("Task job does not belong to this project/message")
            if job.status == "completed":
                if not job.output_asset_ids:
                    raise ProviderError("Completed render has no saved output assets")
                for asset_id in job.output_asset_ids:
                    asset = session.get(Asset, asset_id)
                    if not asset or asset.project_id != project_id or asset.workflow_run_id != job.id or not Path(asset.path).is_file():
                        raise ProviderError("Render output failed project/provenance verification")
            generation = session.scalar(select(GenerationRecord).where(GenerationRecord.job_id == job.id))
            jobs.append({"job_id": job.id, "status": job.status, "name": job_label(job, generation)})
            assets.extend(job.output_asset_ids)
        statuses = {item["status"] for item in jobs}
        from .task_lifecycle import render_state
        state = render_state(statuses)
        return {"state": state, "job_id": job_id, "job_ids": ids, "jobs": jobs, "output_asset_ids": assets,
                "requested_job_count": message.metadata_json.get("local_render_batch_count", 1)}
