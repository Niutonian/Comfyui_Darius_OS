"""Request-scoped visual subject protection, independent of model transport."""
from copy import deepcopy
import json


class SubjectToolGuard:
    def __init__(self, runner, prompt, slot_selector, *, read_only=False, plan=None, reference_context=None):
        self.runner = runner
        self.prompt = prompt
        self.slot_selector = slot_selector
        self.read_only = read_only
        self.plan = plan or (lambda: None)
        self.reference_context = reference_context or (lambda: {})
        self.inspections = {}
        # Preserve the real bridge's activity/cancellation hooks in LangGraph.
        self.__self__ = getattr(runner, "__self__", None)

    def inspect(self, workflow_id, timeout):
        if workflow_id not in self.inspections:
            result = self.runner({"operation": "inspect_workflow", "arguments": {"workflow_id": workflow_id}}, timeout)
            if not isinstance(result, dict) or result.get("error"):
                return result
            self.inspections[workflow_id] = result
        return self.inspections[workflow_id]

    def __call__(self, envelope, timeout):
        # Both native object arguments and the advertised JSON-string form are
        # accepted by the bridge; normalize before inspecting or editing them.
        if "arguments" not in envelope and "arguments_json" in envelope:
            try:
                arguments = json.loads(envelope["arguments_json"])
            except (ValueError, TypeError):
                return {"error": "Tool arguments_json must be a valid JSON object."}
            if not isinstance(arguments, dict):
                return {"error": "Tool arguments_json must be a JSON object."}
            envelope = {**envelope, "arguments": arguments}
            envelope.pop("arguments_json", None)
        operation = envelope.get("operation")
        if operation not in {"prepare_workflow", "prepare_graph", "queue_local_render"}:
            result = self.runner(envelope, timeout)
            if operation == "inspect_workflow" and isinstance(result, dict) and not result.get("error"):
                self.inspections[envelope.get("arguments", {}).get("workflow_id")] = result
            return result
        if self.read_only:
            return {"error": "This is an informational question, not a generation request. Inspect or explain; do not prepare or queue a render."}
        if self.__self__ and (getattr(self.__self__, "workflow_policy", None) or {}).get("purpose") == "image-upscale":
            from .trusted_workflows import pure_upscale
            args = envelope.get("arguments", {})
            inspected = {"graph": args.get("graph")} if operation == "prepare_graph" else self.inspect(args.get("workflow_id"), timeout)
            if isinstance(inspected, dict) and pure_upscale(inspected.get("graph")):
                # Deterministic image processing has no positive conditioning.
                # The bridge still enforces recipe topology, image ownership,
                # binding, validation, and explicit render permission.
                return self.runner(envelope, timeout)
        prompt = self.prompt(timeout)
        if not prompt:
            return {"error": "Resolve the current project's visual subject before preparing or queuing. Ask for clarification if ambiguous."}
        prepared = deepcopy(envelope)
        args = prepared.setdefault("arguments", {})
        plan = self.plan()
        if plan:
            from .visual_plan import input_references
            plan = deepcopy(plan)
            context = self.reference_context()
            for entry in plan.get("shots", []):
                entry["reference_asset_ids"] = input_references(entry.get("reference_asset_ids", []), context)
        shot = None
        if plan:
            shots = plan["shots"]
            brief_id = args.get("brief_id")
            if operation == "queue_local_render" and not brief_id and self.__self__:
                try:
                    brief_id = self.__self__.registry.get(args.get("workflow_id")).generation_brief_id
                except KeyError:
                    pass
            shot = next((item for item in shots if item["id"] == brief_id), None)
            if shot is None and len(shots) == 1:
                shot = shots[0]
            if shot is None:
                return {"error": "Choose a brief_id and prepare a separate workflow for each shot. Do not reuse the first shot for all outputs.",
                        "error_code": "brief_selection_required", "visual_plan": plan, "retryable": False,
                        "recovery": "correct_arguments"}
            prompt = shot["prompt"]
            args["brief_id"] = shot["id"]
            if self.__self__ and getattr(self.__self__, "session_factory", None):
                from .database import Message, Conversation
                with self.__self__.session_factory.begin() as session:
                    source = session.get(Message, self.__self__.message_id)
                    conversation = session.get(Conversation, source.conversation_id) if source else None
                    if not conversation or conversation.project_id != self.__self__.project_id:
                        return {"error": "Visual plan does not belong to this project conversation."}
                    existing = source.metadata_json.get("visual_plan")
                    if existing and existing != plan and source.metadata_json.get("local_render_job_id"):
                        return {"error": "This plan already has render jobs. Use a new message to change its subjects."}
                    source.metadata_json = {**source.metadata_json, "visual_plan": plan}
            if operation != "queue_local_render" and shot["reference_asset_ids"]:
                bound = set((args.get("asset_bindings") or {}).values())
                if not set(shot["reference_asset_ids"]).issubset(bound):
                    return {"error": "Bind this shot's reference images to inspected loader slots before preparing it.",
                            "error_code": "missing_shot_references", "shot": shot, "recovery": "correct_arguments"}
        if operation == "prepare_graph":
            graph = args.get("graph")
            inspected = {"graph": graph}
        else:
            inspected = self.inspect(args.get("workflow_id"), timeout)
            if not isinstance(inspected, dict) or inspected.get("error"):
                return inspected if isinstance(inspected, dict) else {"error": "Workflow inspection failed; nothing was prepared or queued."}
            graph = inspected.get("graph") or {}
        from .render_preview import graph_inputs
        from .workflows import resolve_graph_slot
        from .workflow_registration import manifest
        recipe = inspected.get("recipe_manifest") or manifest(graph) if graph else {}
        entries = graph_inputs(graph)["positive"] if graph else []
        if not entries:
            slot = self.slot_selector(inspected)
            entries = [{"slot": slot, "value": ""}] if slot else []
        if not entries:
            return {"error": "Cannot verify positive conditioning. Inspect the graph's prompt connections before preparing it.", "error_code": "prompt_mapping_required"}
        bindings = args.pop("prompt_bindings", {})
        if operation == "queue_local_render" and self.__self__:
            bindings = self.__self__.registry.get(args.get("workflow_id")).prompt_bindings
        defaults = {item["slot"]: "shot" if item["role"] == "scene" else "preserve"
                    for item in recipe.get("fields", []) if item["role"] in {"scene", "preserve"}}
        bindings = {**defaults, **bindings} if isinstance(bindings, dict) else bindings
        if not isinstance(bindings, dict) or set(bindings) - {entry["slot"] for entry in entries}:
            return {"error": "prompt_bindings must use the positive slots from this workflow inspection."}
        # Distinct regional/dual-encoder prompts need explicit semantic roles.
        if len({entry["value"] for entry in entries}) > 1 and set(bindings) != {entry["slot"] for entry in entries}:
            return {"error": "This workflow has several different positive prompts. Map every slot with prompt_bindings: slot -> 'shot' or 'subject:<character_id>'.",
                    "error_code": "prompt_mapping_required", "positive_slots": entries, "shot": shot,
                    "recovery": "correct_arguments"}
        replacements = {}
        protected = {item["slot"]: item["value"] for item in recipe.get("fields", []) if item["role"] in {"system", "negative", "preserve"}}
        for slot, value in (args.get("overrides") or {}).items():
            if slot in protected and value != protected[slot]:
                return {"error": "Protected workflow instructions cannot be changed by a generation request.", "error_code": "protected_recipe_input", "retryable": False}
        for entry in entries:
            role = bindings.get(entry["slot"], "shot")
            if role == "preserve":
                continue
            if role == "shot":
                replacements[entry["slot"]] = prompt
            else:
                identity = next((s for s in (shot or {}).get("subjects", []) if role == "subject:" + s["id"]), None)
                if not identity or not identity.get("canonical_prompt"):
                    return {"error": "Subject prompt binding needs an identified character with a canonical appearance."}
                replacements[entry["slot"]] = str(identity["name"]) + ": " + identity["canonical_prompt"]
        if operation == "prepare_workflow":
            overrides = args.get("overrides", {})
            if not isinstance(overrides, dict):
                return {"error": "Workflow overrides must be an object."}
            args["overrides"] = {**overrides, **replacements}
        else:
            for slot, text in replacements.items():
                node, field = resolve_graph_slot(graph, slot)
                if operation == "queue_local_render":
                    if graph[node]["inputs"][field] != text:
                        return {"error": "The saved workflow does not contain the resolved subject in positive conditioning. Prepare a corrected copy before queuing; nothing was queued."}
                else:
                    graph[node]["inputs"][field] = text
        if operation != "queue_local_render" and bindings:
            args["prompt_bindings"] = bindings
        return self.runner(prepared, timeout)
