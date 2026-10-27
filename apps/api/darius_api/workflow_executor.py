"""Deterministic recipe execution between a resolved visual brief and ComfyUI.

Every action still passes through SubjectToolGuard, project asset checks, live
validation and the persisted render queue. No provider SDK or graph invention.
"""
import json
import re
from uuid import uuid4
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .workflow_registration import manifest


class ExecutionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workflow_id: str = Field(min_length=1, max_length=300)
    output_kind: Literal["image", "video"]
    prompt: str = Field(min_length=1, max_length=20000)
    output_count: int = Field(ge=1, le=6)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=20)
    allow_render: bool = False
    settings: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=20)


def tool_response(operation, arguments):
    return {"id": "workflow-executor", "output": [{"type": "function_call", "name": "comfyui",
        "call_id": "executor-" + uuid4().hex,
        "arguments": json.dumps({"operation": operation, "arguments": arguments})}]}


def final_response(reply, *, prompt=None, workflow_id=None, state="draft", error_code=None):
    answer = {"reply": reply, "generation_prompt": prompt, "workflow_id": workflow_id,
              "workflow_execution": {"version": 1, "state": state, "error_code": error_code}}
    return {"id": "workflow-executor-final", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps(answer)}]}]}


def tool_history(body):
    calls, history = {}, []
    for item in body.get("input", []):
        try:
            if item.get("type") == "function_call" and item.get("name") == "comfyui":
                from .comfy_arguments import parse_arguments
                call = json.loads(item["arguments"])
                calls[item["call_id"]] = (call["operation"], parse_arguments(call))
            elif item.get("type") == "function_call_output" and item.get("call_id") in calls:
                operation, args = calls[item["call_id"]]
                result = json.loads(item["output"])
                if isinstance(result, dict):
                    history.append((operation, args, result))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return history


class WorkflowExecutor:
    def __init__(self, settings, bridge=None):
        self.settings, self.bridge = settings, bridge

    def progress(self, stage, state="running", **details):
        if self.bridge and hasattr(self.bridge, "on_activity"):
            self.bridge.on_activity(stage, state)
        from .diagnostics import record
        record(self.settings, "workflow_executor", "error" if state == "failed" else "info", stage,
               project_id=getattr(self.bridge, "project_id", None),
               message_id=getattr(self.bridge, "message_id", None), **details)

    def blocked(self, reason, code="workflow_blocked", history=()):
        self.progress("workflow_blocked", "failed", error_code=code, detail=str(reason)[:1000])
        jobs = list(dict.fromkeys(key for op, _, result in history if op == "queue_local_render"
            for key in (result.get("job_ids") or ([result["job_id"]] if result.get("job_id") else []))))
        uncertain_submission = any(op == "queue_local_render" and result.get("error") for op, _, result in history)
        suffix = (" Previously confirmed renders are retained in Background jobs.") if jobs else (
            " No render job was confirmed. Check Background jobs before retrying the saved request." if uncertain_submission else " No render was submitted.")
        response = final_response(reason + suffix, state="blocked", error_code=code)
        from .chat_recovery import recovery_for
        answer = json.loads(response["output"][0]["content"][0]["text"])
        answer["workflow_execution"]["recovery"] = recovery_for(reason, code, has_jobs=bool(jobs) or uncertain_submission)
        response["output"][0]["content"][0]["text"] = json.dumps(answer)
        return response

    @staticmethod
    def preflight(inspection, context, request_text):
        """Check known inputs before asking any model to write a visual brief."""
        graph = inspection.get("graph") or {}
        contract = inspection.get("recipe_manifest") or manifest(graph)
        if contract["status"] != "ready":
            return ("This base recipe needs a one-time input mapping. Open Create → Trusted workflows → Register inputs and resolve the highlighted fields.", "recipe_mapping_required")
        if contract.get("video_slots"):
            return ("This recipe needs a project video input that cannot currently be bound safely. Choose a compatible recipe; saved example videos will not be reused.", "unbound_video_inputs")
        references = context.get("workflow_route", {}).get("reference_asset_ids", [])
        slots = contract.get("image_slots", [])
        from .recipe_adaptation import bind_references
        if references and not slots:
            return ("This recipe has no image input for your reference. Choose an image-capable workflow or remove the reference.", "incompatible_recipe_references")
        try:
            bind_references(graph, slots, references)
        except ValueError:
            return (f"This recipe needs {len(slots)} image inputs, but you supplied {len(references)}. Attach the required images or choose a compatible workflow.", "missing_recipe_references")
        for name in (context.get("execution_settings") or {}):
            if len(contract.get("setting_slots", {}).get(name, [])) != 1:
                return (f"This recipe does not declare an unambiguous {name} setting. Configure it in the base workflow.", "ambiguous_recipe_setting")
        return None

    def next(self, body, request_text, context, prompt, plan=None):
        from .media_intent import output_kind, requested_count
        try:
            intent = ExecutionIntent(workflow_id=context["preferred_workflow_id"], output_kind=output_kind(request_text),
                prompt=prompt, output_count=requested_count(request_text), allow_render=bool(context.get("allow_local_rendering")),
                reference_asset_ids=context.get("workflow_route", {}).get("reference_asset_ids", []),
                settings=context.get("execution_settings") or {})
        except ValidationError:
            return self.blocked("This request needs a valid visual description and between one and six outputs.", "invalid_execution_intent")
        history = tool_history(body)
        if history and history[-1][2].get("error"):
            op, args, result = history[-1]
            attempts = sum(1 for operation, previous, _ in history if operation == op
                and previous.get("workflow_id") == args.get("workflow_id") and previous.get("brief_id") == args.get("brief_id"))
            if op == "prepare_workflow" and result.get("error_code") == "prompt_mapping_required" and attempts < 2:
                self.progress("workflow_retry", operation="register_workflow", attempt=2)
                return tool_response("inspect_workflow", {"workflow_id": intent.workflow_id, "executor_retry": 1, "refresh_registration": True})
            if op in {"inspect_workflow", "prepare_workflow"} and result.get("retryable") is True and attempts < 2:
                self.progress("workflow_retry", operation=op, attempt=2)
                return tool_response(op, {**args, "executor_retry": 1})
            validation = result.get("validation") or {}
            reason = str(result["error"])
            if validation.get("errors"):
                errors = validation["errors"]
                errors = errors if isinstance(errors, list) else [errors]
                reason += ": " + "; ".join(str(error)[:400] for error in errors[:3])
            return self.blocked(reason, result.get("error_code", "workflow_step_failed"), history)
        inspection = next((result for op, args, result in reversed(history)
            if op == "inspect_workflow" and args.get("workflow_id") == intent.workflow_id and not result.get("error")), None)
        if not inspection:
            self.progress("register_workflow", workflow_id=intent.workflow_id)
            return tool_response("inspect_workflow", {"workflow_id": intent.workflow_id})
        problem = self.preflight(inspection, context, request_text)
        if problem:
            return self.blocked(*problem, history=history)
        graph = inspection.get("graph") or {}
        contract = inspection.get("recipe_manifest") or manifest(graph)
        if contract["status"] != "ready":
            return self.blocked("This base recipe needs a one-time input mapping. Open Create → Trusted workflows → Register inputs, resolve the highlighted fields, then send the generation request again.",
                "recipe_mapping_required", history)
        # A trusted routing choice is not blanket permission to execute custom
        # or external nodes. Still prepare a validated draft for explicit review
        # instead of failing queue_local_render after successful preparation.
        from .local_render import LOCAL_NODES
        review_nodes = sorted({node.get("class_type", "") for node in graph.values()} - LOCAL_NODES.keys())
        automatic = intent.allow_render and not review_nodes
        shots = (plan or {}).get("shots") or [{"id": "shot-1", "prompt": intent.prompt, "reference_asset_ids": []}]
        prepared, queued, jobs = {}, {}, []
        for op, args, result in history:
            if result.get("error"):
                continue
            key = args.get("brief_id", "shot-1")
            if op == "prepare_workflow" and result.get("workflow_id"):
                prepared[key] = result["workflow_id"]
            elif op == "queue_local_render" and result.get("job_id"):
                queued[key] = True
                jobs.extend(result.get("job_ids") or [result["job_id"]])
        for shot in shots:
            key = shot["id"]
            if queued.get(key):
                continue
            if key in prepared:
                if automatic:
                    self.progress("queue_local_render", workflow_id=prepared[key], brief_id=key)
                    return tool_response("queue_local_render", {"workflow_id": prepared[key], "brief_id": key})
                continue
            self.progress("compile_workflow", workflow_id=intent.workflow_id, brief_id=key)
            from .visual_plan import input_references
            shot_references = input_references(shot.get("reference_asset_ids", []), context)
            references = list(dict.fromkeys([*shot_references, *intent.reference_asset_ids]))
            slots = contract["image_slots"]
            from .recipe_adaptation import bind_references
            try:
                bindings = bind_references(graph, slots, references)
            except ValueError:
                return self.blocked(f"This recipe has {len(slots)} active image inputs, but the request supplies {len(references)} project references. Attach the required images or choose a compatible recipe.",
                    "missing_recipe_references", history)
            if references and not slots:
                return self.blocked("This recipe has no active image input for the requested project references. Choose an image-capable recipe.",
                    "incompatible_recipe_references", history)
            if contract.get("video_slots"):
                return self.blocked("This recipe contains active video-loader inputs that are not bound to project media. Its saved example videos cannot be reused. Register a compatible input setup before rendering.",
                    "unbound_video_inputs", history)
            overrides = {slot: shot["prompt"] for slot in contract["scene_slots"]}
            settings = dict(intent.settings)
            for name, value in settings.items():
                targets = contract.get("setting_slots", {}).get(name, [])
                if len(targets) != 1:
                    return self.blocked(f"The recipe does not declare one unambiguous {name} setting. Configure that value in the base workflow before rendering.",
                        "ambiguous_recipe_setting", history)
                overrides[targets[0]] = value
            if contract.get("processing_only"):
                scale = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:x|times)\b", request_text, re.I)
                if scale:
                    scale_slot = next((f"{node_id}.scale_by" for node_id, node in graph.items() if "scale_by" in node.get("inputs", {})), None)
                    if scale_slot:
                        overrides[scale_slot] = float(scale[1])
            from .chat_labels import intent_label
            args = {"workflow_id": intent.workflow_id, "name": intent_label(context, shot["prompt"]),
                    "brief_id": key, "output_kind": intent.output_kind,
                    "capability": ("image-to-video" if references else "text-to-video") if intent.output_kind == "video" else ("image-to-image" if references else "text-to-image"),
                    "overrides": overrides, "asset_bindings": bindings,
                    "prompt_bindings": {item["slot"]: "shot" if item["role"] == "scene" else "preserve"
                        for item in contract["fields"] if item["role"] in {"scene", "preserve"}},
                    "expected_recipe_digest": contract.get("contract_digest", contract["graph_digest"]), "seed_mode": "randomize"}
            self.progress("compile_workflow", "complete", workflow_id=intent.workflow_id, brief_id=key)
            return tool_response("prepare_workflow", args)
        if jobs:
            self.progress("workflow_queued", "complete", job_ids=list(dict.fromkeys(jobs)))
            response = final_response("Your render request is queued. Follow progress in Background jobs.", state="queued")
            answer = json.loads(response["output"][0]["content"][0]["text"])
            answer["workflow_execution"]["job_ids"] = list(dict.fromkeys(jobs))
            response["output"][0]["content"][0]["text"] = json.dumps(answer)
            return response
        if prepared:
            self.progress("workflow_awaiting_approval", "complete")
            reason = ("This recipe contains nodes requiring explicit approval: " + ", ".join(review_nodes) + "." if review_nodes
                      else "Local rendering is disabled for this project.")
            return final_response("The validated workflow draft is ready for review. " + reason + " Use Review generation to approve it; no render was submitted.",
                prompt=shots[0]["prompt"], workflow_id=prepared[shots[0]["id"]], state="awaiting_approval")
        return self.blocked("The recipe did not produce a validated draft.", history=history)
