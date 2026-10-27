"""Live Comfy MCP tools for conversation; rendering still goes through the job worker."""
from __future__ import annotations

import json
import time
import shutil
import hashlib
from contextlib import contextmanager
from uuid import uuid4
from pathlib import Path

from .providers import ComfyMcpProvider, ProviderError
from .comfy_preflight import validate_graph
from .services import register_workflows
from .workflows import WorkflowContract, resolve_graph_slot
from .database import Asset


OPERATIONS = ["asset_details", "rename_asset", "list_assets", "view_assets", "discover_workflows", "list_workflows", "inspect_workflow", "search_nodes", "inspect_node", "search_models", "model_folders", "upload_asset", "system_stats", "prepare_workflow", "validate_graph", "prepare_graph", "queue_local_render", "job_status", "create_character", "create_scene", "create_shot", "update_character", "update_scene", "update_shot"]
OPERATIONS.append("present_assets")
TOOL_DEFINITIONS = [{
    "type": "function", "name": "comfyui", "strict": True,
    "description": (
        "Control the live local ComfyUI through Comfy MCP. arguments_json is a JSON object. "
        "asset_details: {asset_id:string}; returns saved project asset metadata and generation seeds. "
        "rename_asset: {asset_id:string,name:string}; changes the project's asset display name when requested. "
        "prepare_workflow and prepare_graph accept seed_mode: 'randomize' (default) or 'preserve'. "
        "Every new generation gets fresh seeds by default. For an explicit seed or same-seed request, set the inspected seed inputs and seed_mode preserve. "
        "list_assets: {query?:string,kind?:'image'|'video'|'audio',limit?:integer,offset?:integer}; finds active-project media by saved prompt/name/id, newest first. "
        "present_assets: {action:'open'|'gallery'|'select'|'close'|'next'|'previous'|'play'|'pause'|'stop'|'restart'|'mute'|'unmute'|'seek',asset_ids?:[string],index?:integer,autoplay?:boolean,seconds?:number}; open shows 1-12 originals full size; gallery shows up to 48 numbered project assets; select requires the visible gallery IDs and a zero-based index; playback controls require exactly one video/audio ID, seek uses a relative delta up to 600 seconds. autoplay only requests playback for open/select; browsers may require a tap. Use for explicit user viewing/playback requests, never as rendering or model vision. Never invent IDs or claim playback succeeded. "
        "view_assets: {asset_ids:[string]}; shows actual image pixels to the MODEL for 1-4 project images, not a full-size view on the user's screen. "
        "discover_workflows: {query?:string,output_kind:'image'|'video',source_kind:'image'|'none',limit?:integer}; returns up to 30 saved workflows and ranks managed Darius defaults before custom workflows. "
        "list_workflows: {name?:string,limit?:integer}; inspect_workflow: {workflow_id:string}; "
        "search_nodes: {query:string}; inspect_node: {name:string}; search_models: {query:string,type?:string}; model_folders: {}; "
        "upload_asset: {asset_id:string}; copies an asset from the active project into ComfyUI input storage and returns its image/file name. "
        "system_stats: {}. inspect_workflow returns agent slots and a converted API graph. "
        "prepare_workflow: {workflow_id:string,overrides:{slot:value},asset_bindings?:{slot:asset_id},name:string,output_kind:'image'|'video'|'audio',capability:string}; "
        "asset_bindings uploads and binds project images to inspected LoadImage.image slots, preserving source provenance. "
        "copies a saved workflow, changes inspected slots, validates it and registers a new draft without running. "
        "When the user switches workflow families, inspect the requested saved workflow and prefer prepare_workflow "
        "with its own slots. Reuse the creative prompt, not node IDs or wiring from the previous family. "
        "For dynamic image inputs, use the exact template.names returned by inspect_node; never invent slot names. "
        "validate_graph: {graph:object}; prepare_graph: {graph:object,name:string,output_kind:string,capability:string}; "
        "graph is API-format node-id -> {class_type,inputs}. Build or rewrite arbitrary graphs using installed node schemas. "
        "Output nodes must have filename_prefix inputs for provenance. Supported capabilities: text-to-image, "
        "image-to-image,text-to-video,image-to-video,video-to-video,character-sheet,face-consistency,lip-sync. "
        "queue_local_render: {workflow_id:string}; queues a prepared draft and starts a worker ONLY with "
        "the project's standing local rendering permission and verified local nodes. "
        "Use only when the user asks to render/generate now, never for a question, inspection, or draft-only request. "
        "For repeated takes, queue_local_render derives 1–6 outputs and deduplicates retries. "
        "For different shots, use the visual_plan returned by the subject guard: prepare a separate workflow "
        "with brief_id:'shot-1' (etc.) and queue each prepared workflow. Each slot is deduplicated separately. "
        "prepare_workflow/prepare_graph accept brief_id and prompt_bindings:{slot:'shot'|'subject:<character_id>'}. "
        "When multiple positive prompts differ, map every positive slot to its semantic role; never reuse slots "
        "from another workflow. Bind every shot reference using asset_bindings. "
        "job_status: {job_id:string}; checks this project's job. "
        "create_character: {name:string,description?:string,canonical_prompt?:string,continuity_notes?:string,approved_reference_asset_ids?:string[]}; "
        "create_scene: {number:integer,title:string,description?:string,screenplay_text?:string,location?:string,time_of_day?:string,mood?:string,status?:string}; "
        "create_shot: {scene_id:string,number:integer,description?:string,shot_type?:string,camera_motion?:string,duration_target?:number,dialogue?:string,status?:string,selected_asset_id?:string}; "
        "update_character/update_scene/update_shot accept the record id plus only fields to change. "
        "These story tools are limited to the active project and change its production bible; use them only when the user explicitly asks to create or edit a story record. "
        "No tool overwrites an original, installs software, or deletes user files. "
        "For a draft-only request, return the workflow_id and generation_prompt for review. "
        "For an explicit render-now request with local rendering already enabled, call queue_local_render after preparation."
    ),
    "parameters": {"type": "object", "properties": {
        "operation": {"type": "string", "enum": OPERATIONS},
        "arguments_json": {"type": "string"}},
        "required": ["operation", "arguments_json"], "additionalProperties": False},
}]


class ComfyAssistantTools:
    def finish_auto_render(self, workflow_id):
        """Finish a prepared render request even if the model stops at a draft."""
        from .database import Message, Conversation
        from .local_render import permission_enabled, requests_render, message_render_request

        if not self.session_factory or not self.project_id or not self.message_id:
            return None
        with self.session_factory() as session:
            source = session.get(Message, self.message_id)
            conversation = session.get(Conversation, source.conversation_id) if source else None
            if (not source or source.role != "user" or not conversation
                    or conversation.project_id != self.project_id
                    or not permission_enabled(session, self.project_id)
                    or not requests_render(message_render_request(session, source))):
                return None
        return self.call({"operation": "queue_local_render", "arguments": {"workflow_id": workflow_id}})

    @staticmethod
    def _compact(value):
        if isinstance(value, dict):
            return {key: (item[:20] if key in {"choices", "enum", "values"} and isinstance(item, list) else ComfyAssistantTools._compact(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [ComfyAssistantTools._compact(item) for item in value]
        return value

    def __init__(self, settings, registry, session_factory, on_activity=None, project_id=None, message_id=None):
        self.settings = settings
        self.registry = registry
        self.session_factory = session_factory
        self.provider = ComfyMcpProvider(settings)
        self.on_activity = on_activity or (lambda *_: None)
        self.project_id = project_id
        self.message_id = message_id
        self.source_asset_ids = []
        self.viewed_asset_ids = []
        self.converted_graphs = {}
        self.workflow_policy = None
        self.canvas_target = None
        self.trusted_graph_structures = []
        self.trusted_protected_inputs = []
        self.block_party_graphs = set()

    def _require_trusted(self, workflow_id):
        if not (self.workflow_policy or {}).get("enabled"):
            return
        if workflow_id in self.workflow_policy.get("allowed_ids", []):
            return
        try:
            contract = self.registry.get(workflow_id)
        except KeyError:
            contract = None
        if contract and contract.project_id == self.project_id and contract.generation_task_id == self.message_id:
            return
        raise ProviderError("This workflow is outside the trusted list. Choose a trusted recipe or explicitly select a different workflow in chat.")

    def call(self, request: dict, timeout: int = 30) -> dict:
        # A real conversation source never grants write/execute capability,
        # even if an older checkpoint or forged envelope calls this directly.
        if self.session_factory and self.message_id:
            if request.get("operation") not in {"asset_details", "list_assets", "view_assets", "job_status", "present_assets"}:
                return {"error":"Chat is a creative text helper. Apply prompts through Use in board and generate from the board.", "error_code":"chat_text_only", "retryable":False}
        from .task_control import check_task_control, TaskStopped
        try:
            check_task_control(self)
        except TaskStopped:
            raise
        except ProviderError as exc:
            return {"error": str(exc)}
        operation = request.get("operation")
        if operation not in OPERATIONS:
            raise ProviderError("Unknown ComfyUI operation")
        if self.canvas_target is not None and operation in {"prepare_workflow", "prepare_graph", "queue_local_render", "upload_asset"}:
            return {"error": "The selected MOSS board uses its immutable saved layout. Use Generate composition in Canvas; do not prepare or queue a different workflow.", "error_code": "canvas_snapshot_required", "retryable": False}
        from .comfy_arguments import parse_arguments
        try:
            args = parse_arguments(request)
        except ValueError as exc:
            self.on_activity(operation, "failed")
            return {"error": str(exc), "error_code": "invalid_arguments", "retryable": True,
                    "instruction": "Correct the arguments and retry. No action was executed."}
        self.on_activity(operation, "running")
        from .diagnostics import record
        record(self.settings, "comfyui", "info", "tool_started", operation=operation,
               project_id=self.project_id, message_id=self.message_id)
        # Conversion and validation of larger video graphs can legitimately
        # take longer than the lightweight catalog and metadata operations.
        # Stay within the assistant graph's overall deadline while avoiding a
        # fixed 25-second cutoff halfway through an otherwise healthy MCP run.
        expensive = operation in {
            "inspect_workflow", "prepare_workflow", "validate_graph", "prepare_graph",
        }
        operation_timeout = min(timeout, 120 if expensive else 25)
        self.deadline = time.monotonic() + operation_timeout
        try:
            result = self._call(operation, args, operation_timeout)
        except (ProviderError, ValueError, OSError, KeyError, TypeError) as exc:
            record(self.settings, "comfyui", "error", "tool_failed", operation=operation,
                   project_id=self.project_id, message_id=self.message_id, error=str(exc)[:2000])
            self.on_activity(operation, "failed")
            from .workflow_errors import failure_details
            return failure_details(exc)
        if result.get("error"):
            from .workflow_errors import failure_details
            result = {**failure_details(result["error"]), **result}
        self.on_activity(operation, "failed" if result.get("error") else "complete")
        record(self.settings, "comfyui", "error" if result.get("error") else "info", "tool_finished",
               operation=operation, project_id=self.project_id, message_id=self.message_id,
               error=result.get("error"), timeout_seconds=operation_timeout)
        # Bound tool context; never silently present incomplete graph data as complete.
        encoded = json.dumps({key: value for key, value in result.items() if key != "_image_content"}, ensure_ascii=False, default=str)
        if len(encoded) > 100_000:
            return {"truncated": True, "preview": encoded[:100_000], "instruction": "Result is truncated. Narrow your inspection; do not reconstruct a graph from this preview."}
        return result

    def _run(self, args, timeout):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderError("ComfyUI tool timed out")
        return self.provider._run(["--json", *args], min(timeout, remaining)).get("data") or {}

    @staticmethod
    @contextmanager
    def _working_directory(root: Path):
        """Create a short-lived work directory with inherited Windows ACLs.

        Python 3.12's ``TemporaryDirectory`` requests mode 0700. On some
        Windows volumes that is translated into an unusable ACL, so even the
        creating API process cannot copy the workflow into it.
        """
        directory = root / f"task-{uuid4().hex}"
        directory.mkdir()
        try:
            yield directory
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    @staticmethod
    def _text(args, key):
        value = args.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 500 or value.startswith("-"):
            raise ProviderError(f"{key} must be a nonempty value, not a command flag")
        return value

    def _saved_copy(self, args, directory, timeout):
        workflow_id = self._text(args, "workflow_id")
        self._require_trusted(workflow_id)
        path = Path(workflow_id)
        if path.is_absolute() or ".." in path.parts or ":" in workflow_id or "\\" in workflow_id:
            raise ProviderError("Choose a relative workflow id from list_workflows")
        target = directory / "source.json"
        contract = None
        if self.registry:
            try:
                contract = self.registry.get(workflow_id)
            except KeyError:
                pass
        if contract:
            if self.project_id and self.session_factory:
                from .assistant_context import workflow_available
                with self.session_factory() as session:
                    if not workflow_available(session, self.project_id, contract):
                        raise ProviderError("Workflow belongs to another project. Choose a shared workflow or one prepared here.")
            shutil.copy2(self.provider._workflow_path(contract.workflow_reference), target)
        else:
            from .workflow_catalog import workflow_source_path
            source = workflow_source_path(self.settings, workflow_id)
            if source is not None:
                shutil.copy2(source[1], target)
            else:
                self._run(["workflow", "get", workflow_id, "--out", str(target)], timeout)
        if not target.is_file() or target.stat().st_size > 5_000_000:
            raise ProviderError("Workflow is missing or too large to inspect")
        return target

    def _story_record(self, operation, args):
        """Create or edit one production-bible record, always scoped to this project."""
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError
        from .database import Character, CharacterAssetReference, Scene, Shot, utcnow
        from .services import add_event
        from .schemas import CharacterCreate, SceneCreate, ShotCreate

        kind = operation.removeprefix("create_").removeprefix("update_")
        model = {"character": Character, "scene": Scene, "shot": Shot}[kind]
        record_id = args.get("id") or args.get(f"{kind}_id")
        if operation.startswith("update_") and not isinstance(record_id, str):
            raise ProviderError(f"{kind}_id is required")
        clean = {key: value for key, value in args.items() if key not in {"id", f"{kind}_id", "scene_id"}}
        try:
            if operation == "create_character":
                payload = CharacterCreate.model_validate(clean)
            elif operation == "create_scene":
                payload = SceneCreate.model_validate(clean)
            elif operation == "create_shot":
                scene_id = self._text(args, "scene_id")
                payload = ShotCreate.model_validate(clean)
            else:
                allowed = {
                    "character": {"name", "description", "canonical_prompt", "negative_prompt", "continuity_notes", "voice_profile_id", "metadata"},
                    "scene": {"number", "title", "description", "screenplay_text", "location", "time_of_day", "mood", "status"},
                    "shot": {"number", "description", "shot_type", "camera_motion", "duration_target", "dialogue", "status", "selected_asset_id"},
                }[kind]
                unknown = set(clean) - allowed
                if unknown:
                    raise ProviderError(f"unknown {kind} fields: {', '.join(sorted(unknown))}")
                if not clean:
                    raise ProviderError("provide at least one field to update")
                payload = clean
        except ValueError as exc:
            raise ProviderError(f"invalid {kind} data: {exc}") from exc

        try:
            with self.session_factory.begin() as session:
                if operation.startswith("create_"):
                    if kind == "character":
                        existing = session.scalar(select(Character).where(Character.project_id == self.project_id, Character.name == payload.name.strip()))
                        if existing:
                            return {"record_type": kind, "record": {column.name: getattr(existing, column.name) for column in model.__table__.columns}, "project_id": self.project_id, "note": "A character with this name already exists; reused it idempotently."}
                    if kind == "shot":
                        scene = session.get(Scene, scene_id)
                        if not scene or scene.project_id != self.project_id:
                            raise ProviderError("scene does not belong to this project")
                        values = payload.model_dump()
                        number = values["number"]
                        while session.scalar(select(Shot).where(Shot.scene_id == scene_id, Shot.number == number)):
                            number += 1
                        if number != values["number"]:
                            values["number"] = number
                            adjusted_note = f"The requested shot number was occupied; assigned the next available number ({number})."
                        selected = values.get("selected_asset_id")
                        if selected and (not (asset := session.get(Asset, selected)) or asset.project_id != self.project_id):
                            raise ProviderError("selected asset does not belong to this project")
                        record = Shot(id=str(uuid4()), scene_id=scene_id, **values)
                        event_project = scene.project_id
                    else:
                        values = payload.model_dump()
                        adjusted_note = None
                        if kind == "scene":
                            number = values["number"]
                            while session.scalar(select(Scene).where(Scene.project_id == self.project_id, Scene.number == number)):
                                number += 1
                            if number != values["number"]:
                                values["number"] = number
                                adjusted_note = f"The requested scene number was occupied; assigned the next available number ({number})."
                        references = values.pop("approved_reference_asset_ids", []) if kind == "character" else []
                        if kind == "character":
                            values["metadata_json"] = values.pop("metadata", {})
                        if kind == "character":
                            for asset_id in references:
                                asset = session.get(Asset, asset_id)
                                if not asset or asset.project_id != self.project_id or asset.kind != "image":
                                    raise ProviderError("approved reference must be an image in this project")
                        record = model(id=str(uuid4()), project_id=self.project_id, **values)
                        if kind == "character":
                            session.flush()
                            for asset_id in references:
                                session.add(CharacterAssetReference(character_id=record.id, asset_id=asset_id, approved=True))
                        event_project = self.project_id
                    session.add(record)
                    session.flush()
                    add_event(session, event_project, f"{kind}.created", kind, record.id, {"name": getattr(record, "name", None), "number": getattr(record, "number", None)})
                else:
                    record = session.get(model, record_id)
                    owner = session.get(Scene, record.scene_id) if record and kind == "shot" else record
                    if not owner or owner.project_id != self.project_id:
                        raise ProviderError(f"{kind} does not belong to this project")
                    schema = {"character": CharacterCreate, "scene": SceneCreate, "shot": ShotCreate}[kind]
                    current = {key: getattr(record, "metadata_json" if key == "metadata" else key)
                               for key in schema.model_fields if hasattr(record, "metadata_json" if key == "metadata" else key)}
                    validated = schema.model_validate({**current, **payload}).model_dump()
                    payload = {key: validated[key] for key in payload}
                    selected = payload.get("selected_asset_id")
                    if selected and (not (asset := session.get(Asset, selected)) or asset.project_id != self.project_id):
                        raise ProviderError("selected asset does not belong to this project")
                    for key, value in payload.items():
                        setattr(record, "metadata_json" if kind == "character" and key == "metadata" else key, value)
                    record.updated_at = utcnow()
                    event_project = self.project_id
                    add_event(session, event_project, f"{kind}.updated", kind, record.id, {"fields": list(payload)})
                result = {"record_type": kind, "record": {column.name: getattr(record, column.name) for column in model.__table__.columns}, "project_id": self.project_id}
                if 'adjusted_note' in locals() and adjusted_note:
                    result["note"] = adjusted_note
                return result
        except IntegrityError as exc:
            raise ProviderError(f"{kind} conflicts with an existing record in this project") from exc

    def _call(self, operation, args, timeout):
        if self.session_factory and self.message_id and operation not in {"asset_details", "list_assets", "view_assets", "job_status", "present_assets"}:
            raise ProviderError("Chat cannot modify projects, prepare workflows or submit jobs. Use the board controls.")
        if (self.workflow_policy or {}).get("enabled"):
            if operation in {"discover_workflows", "list_workflows"}:
                from .trusted_workflows import summary
                from .base_recipes import recipes
                available = recipes(self.settings, self.registry)
                workflows = [available[key] if key in available else self.registry.get(key) for key in self.workflow_policy.get("allowed_ids", [])]
                kind = args.get("output_kind")
                from .trusted_workflows import _workflow_words
                query = _workflow_words(self._text(args, "name")) if args.get("name") else ""
                limit = max(1, min(100, int(args.get("limit", 100))))
                matches = [w for w in workflows if (not kind or w.output.kind == kind)
                           and (not query or query in _workflow_words(w.name + " " + w.id))]
                return {"workflows": [{**summary(w), "workflow_id": w.id} for w in matches[:limit]],
                        "limit": limit, "total": len(matches),
                        "note": "Trusted project recipes only. Inspect the selected template; the full catalog was not searched."}
            if operation == "queue_local_render":
                self._require_trusted(self._text(args, "workflow_id"))
        # Reference provenance belongs to this prepared graph, not earlier tool calls.
        if operation in {"prepare_workflow", "prepare_graph"}:
            self.source_asset_ids = []
            if self.message_id and self.session_factory:
                from .database import Message, Conversation
                from .media_intent import is_writing_request
                with self.session_factory() as session:
                    source = session.get(Message, self.message_id)
                    conversation = session.get(Conversation, source.conversation_id) if source else None
                    if source and conversation and conversation.project_id == self.project_id and is_writing_request(source.content):
                        raise ProviderError("This request is for writing scenes, not generating media. Write the requested text or use the story-record tools; do not prepare a render.")
        trusted_saved_images = {}
        if operation in {"create_character", "create_scene", "create_shot", "update_character", "update_scene", "update_shot"}:
            return self._story_record(operation, args)
        if operation in {"asset_details", "rename_asset"}:
            from .database import GenerationRecord
            from .services import add_event
            from sqlalchemy import select
            with self.session_factory.begin() as session:
                asset = session.get(Asset, self._text(args, "asset_id"))
                if not asset or asset.project_id != self.project_id:
                    raise ProviderError("Asset does not belong to this project")
                if operation == "rename_asset":
                    name = self._text(args, "name").strip()
                    if not name or len(name) > 200 or any(c in name for c in "\\/\r\n"):
                        raise ProviderError("Use a display name of 1–200 characters without path separators")
                    asset.metadata_json = {**asset.metadata_json, "display_name": name}
                    add_event(session, self.project_id, "asset.renamed", "asset", asset.id, {"name": name})
                generation = session.scalar(select(GenerationRecord).where(GenerationRecord.job_id == asset.workflow_run_id))
                return {"asset_id": asset.id, "metadata": asset.metadata_json, "generation": {"seed": generation.seed, "parameters": generation.parameters, "prompt": generation.prompt, "workflow_id": generation.workflow_definition_id} if generation else None}
        if operation == "list_assets":
            from .assistant_assets import list_project_assets
            return list_project_assets(self.session_factory, self.project_id, args.get("query", ""), args.get("kind"), args.get("limit", 20), args.get("offset", 0))
        if operation == "present_assets":
            from .asset_presentation import presentation_action
            with self.session_factory() as session:
                receipt = presentation_action(session, self.settings, self.project_id, args.get("action", "open"), args.get("asset_ids"), index=args.get("index"), autoplay=args.get("autoplay", False), seconds=args.get("seconds"))
            return {"presentation_action": receipt, "instruction": "The originating Darius client will apply this viewer action after the verified reply. This is presentation only: no model vision, rendering, file changes, or new browser tabs."}
        if operation == "view_assets":
            from .assistant_assets import view_project_assets
            if len(self.viewed_asset_ids) >= 8:
                raise ProviderError("Already inspected eight images in this reply. Narrow the selection before continuing.")
            result = view_project_assets(self.session_factory, self.settings, self.project_id, args.get("asset_ids"))
            self.viewed_asset_ids = list(dict.fromkeys([*self.viewed_asset_ids, *result["viewed_asset_ids"]]))
            return result
        if operation == "discover_workflows":
            from .workflow_catalog import discover_workflows
            return discover_workflows(self.settings, args.get("query", ""), args.get("output_kind", "video"), args.get("source_kind", "image"), args.get("limit", 30))
        if operation == "queue_local_render":
            from .local_render import queue_local_render
            return queue_local_render(self.settings, self.registry, self.session_factory,
                                      self.project_id, self.message_id, self._text(args, "workflow_id"))
        if operation == "job_status":
            from .database import Job
            with self.session_factory() as session:
                job = session.get(Job, self._text(args, "job_id"))
                if not job or job.project_id != self.project_id:
                    raise ProviderError("Job does not belong to this project")
                return {"job_id": job.id, "status": job.status, "detail": job.status_message,
                        "error": job.error_detail, "output_asset_ids": job.output_asset_ids} if job.error_detail else {
                            "job_id": job.id, "status": job.status, "detail": job.status_message,
                            "output_asset_ids": job.output_asset_ids}
        if operation == "list_workflows":
            limit = max(1, min(100, int(args.get("limit", 100))))
            if self.settings.comfy_workflow_defaults_root is not None and self.registry is not None:
                from .base_recipes import recipes
                from .trusted_workflows import summary, _workflow_words
                query = _workflow_words(self._text(args, "name")) if args.get("name") else ""
                available = recipes(self.settings, self.registry)
                matches = [w for w in available.values() if not query or query in _workflow_words(w.name + " " + w.id)]
                matches.sort(key=lambda w: (w.name.casefold(), w.id))
                return {"workflows": [{**summary(w), "workflow_id": w.id} for w in matches[:limit]],
                        "count": len(matches[:limit]), "total": len(matches), "limit": limit,
                        "note": "Darius base recipes, including Block Party imports and cloud operations. Generated drafts are excluded. Inspect before use; availability is not readiness or approval."}
            command = ["workflow", "list", "--limit", str(limit)]
            if args.get("name"):
                command.extend(["--name", self._text(args, "name")])
            result = self._run(command, timeout)
            result["limit"] = limit
            result["note"] = "At most limit results; filter by name to narrow a large collection."
            return result
        if operation == "system_stats":
            return self._run(["system-stats"], timeout)
        if operation == "search_nodes":
            return self._run(["nodes", "search", self._text(args, "query"), "--limit", "20"], timeout)
        if operation == "inspect_node":
            return self._run(["nodes", "show", self._text(args, "name")], timeout)
        if operation == "search_models":
            command = ["models", "search", "--text", self._text(args, "query"), "--limit", "50"]
            if args.get("type"):
                command.extend(["--type", self._text(args, "type")])
            return self._run(command, timeout)
        if operation == "model_folders":
            return self._run(["models", "list-folders"], timeout)
        root = self.settings.data_dir / "assistant-workflows"
        root.mkdir(parents=True, exist_ok=True)
        with self._working_directory(root) as directory:
            if operation == "upload_asset":
                asset_id = self._text(args, "asset_id")
                with self.session_factory() as session:
                    asset = session.get(Asset, asset_id)
                    if not asset or not self.project_id or asset.project_id != self.project_id:
                        raise ProviderError("Asset does not belong to this project")
                    from .assistant_assets import managed_asset_path
                    source = managed_asset_path(asset, self.settings)
                    target = directory / f"darius-{asset.id}{source.suffix}"
                    shutil.copy2(source, target)
                result = self._run(["upload", str(target), "--no-overwrite"], timeout)
                uploaded = result.get("uploads", [result])
                if not isinstance(uploaded, list) or len(uploaded) != 1 or not isinstance(uploaded[0], dict):
                    raise ProviderError("ComfyUI upload did not return exactly one file")
                item = uploaded[0]
                result = {"name": item.get("name") or item.get("cloud_name"), "subfolder": item.get("subfolder", ""), "type": item.get("type", "input")}
                self.source_asset_ids.append(asset_id)
                return {"asset_id": asset_id, "upload": result}
            if operation in {"inspect_workflow", "prepare_workflow"}:
                source = self._saved_copy(args, directory, timeout)
                document = json.loads(source.read_text(encoding="utf-8-sig"))
                api_format = isinstance(document, dict) and bool(document) and all(isinstance(node, dict) and "class_type" in node for node in document.values())
                try:
                    conversion_key = hashlib.sha256(source.read_bytes()).hexdigest()
                    cached = self.converted_graphs.get(conversion_key)
                    if cached is None and not args.get("refresh_registration"):
                        from .workflow_registration import compiled
                        cached = compiled(self.settings, args["workflow_id"])
                    graph = (document if api_format else json.loads(json.dumps(cached)) if cached is not None
                             else self._run(["run", "--workflow", str(source), "--print-prompt", "--no-notify"], timeout).get("prompt"))
                    if not api_format and isinstance(graph, dict) and graph:
                        self.converted_graphs[conversion_key] = json.loads(json.dumps(graph))
                except ProviderError as exc:
                    from .workflow_catalog import record_conversion
                    record_conversion(self.settings, args["workflow_id"], False, error=exc)
                    raise ProviderError(f"Cannot convert workflow {args['workflow_id']!r}: {exc}. This candidate is unavailable; continue inspecting other returned workflows and do not claim this workflow is ready.") from exc
                if not isinstance(graph, dict) or not graph:
                    raise ProviderError("ComfyUI did not return a converted API graph")
                from .workflow_catalog import record_conversion
                record_conversion(self.settings, args["workflow_id"], True)
                from .workflow_registration import register
                recipe_manifest = register(self.settings, args["workflow_id"], graph, expected_source=conversion_key)
                if recipe_manifest.get("block_party"):
                    from .trusted_workflows import graph_structure
                    from .block_party import digest as package_digest
                    self.block_party_graphs.add(package_digest(graph_structure(graph)))
                    from .block_party_readiness import check_readiness
                    readiness = check_readiness(self.settings, args["workflow_id"], graph=graph)
                    recipe_manifest["readiness"] = readiness
                    if not readiness["ready"]:
                        raise ProviderError("Block Party recipe is not ready: " + "; ".join(item["message"] for item in readiness["issues"][:4]) + ". Prepare it in Block Party and check dependencies again; no render was submitted.")
                expected = args.get("expected_recipe_digest")
                if expected and recipe_manifest.get("contract_digest") != expected:
                    raise ProviderError("The base recipe changed since inspection. Register its current version before preparing another draft.")
                slots = {"slots": [{"address": f"{node_id}.{key}", "value": value, "node_type": node.get("class_type")} for node_id, node in graph.items() for key, value in node.get("inputs", {}).items() if isinstance(value, (str, int, float, bool))]}
                if args["workflow_id"].startswith("assistant-") and self.registry:
                    inherited = self.registry.get(args["workflow_id"]).source_asset_ids
                    with self.session_factory() as session:
                        for asset_id in inherited:
                            asset = session.get(Asset, asset_id)
                            if not asset or asset.project_id != self.project_id:
                                raise ProviderError("Workflow references another project's asset")
                    if operation == "prepare_workflow" and not (self.workflow_policy or {}).get("enabled"):
                        self.source_asset_ids = list(dict.fromkeys([*self.source_asset_ids, *inherited]))
                    if inherited and not (self.workflow_policy or {}).get("enabled"):
                        trusted_saved_images = {f"{node_id}.image": node.get("inputs", {}).get("image")
                            for node_id, node in graph.items() if node.get("class_type") in {"LoadImage", "LoadImageMask"}}
                if operation == "prepare_workflow":
                    overrides = args.get("overrides", {})
                    if not isinstance(overrides, dict) or len(overrides) > 100:
                        raise ProviderError("overrides must be a slot-to-value object with at most 100 entries")
                    from .block_party import enforce_overrides
                    enforce_overrides(recipe_manifest, overrides, args.get("asset_bindings", {}))
                    protected = {item["slot"]: item["value"] for item in recipe_manifest["fields"] if item["role"] in {"system", "negative", "preserve"}}
                    if any(slot in protected and value != protected[slot] for slot, value in overrides.items()):
                        raise ProviderError("Generation overrides cannot change protected workflow instructions or conditioning.")
                    for slot, value in overrides.items():
                        if not isinstance(slot, str) or not isinstance(value, (str, int, float, bool)):
                            raise ProviderError("Invalid workflow slot override")
                        node_id, key = resolve_graph_slot(graph, slot)
                        if (self.workflow_policy or {}).get("enabled") and isinstance(graph[node_id]["inputs"][key], list):
                            raise ProviderError("Trusted recipe overrides can change scalar inputs, not node connections.")
                        graph[node_id]["inputs"][key] = value
                if operation == "inspect_workflow":
                    from .render_preview import graph_inputs
                    if (self.workflow_policy or {}).get("enabled"):
                        from .trusted_workflows import graph_structure
                        self.trusted_graph_structures.append(graph_structure(graph))
                        self.trusted_protected_inputs.append((graph_structure(graph), {item["slot"]: item["value"] for item in recipe_manifest["fields"] if item["role"] in {"system", "negative", "preserve"}}))
                    self.on_activity("register_workflow", "complete")
                    return {"workflow_id": args["workflow_id"], "slots": slots, "graph": graph,
                            "recipe_manifest": recipe_manifest,
                            "prompt_structure": graph_inputs(graph),
                            "image_binding_slots": [f"{node_id}.image" for node_id, node in graph.items() if node.get("class_type") in {"LoadImage", "LoadImageMask"} and "image" in node.get("inputs", {})],
                            "note": "Use asset_bindings to replace saved example images with project assets. Inspect switches and connected inputs to ensure the selected image is actually used."}
            else:
                graph = args.get("graph")
                from .trusted_workflows import graph_structure
                from .block_party import digest as package_digest
                if package_digest(graph_structure(graph)) in self.block_party_graphs:
                    raise ProviderError("Block Party recipes must use prepare_workflow with declared inputs, not prepare_graph.")
                if (self.workflow_policy or {}).get("enabled"):
                    from .trusted_workflows import graph_structure
                    if graph_structure(graph) not in self.trusted_graph_structures:
                        raise ProviderError("Trusted mode requires an inspected template copy with the same nodes and connections. Use prepare_workflow with input overrides; do not invent a new graph.")
                    baselines = [values for structure, values in self.trusted_protected_inputs if structure == graph_structure(graph)]
                    if baselines and not any(all(graph[resolve_graph_slot(graph, slot)[0]]["inputs"][resolve_graph_slot(graph, slot)[1]] == value for slot, value in values.items()) for values in baselines):
                        raise ProviderError("A copied graph changed protected workflow instructions. Rebuild from the registered base.")
            if not isinstance(graph, dict) or not graph or len(graph) > 500:
                raise ProviderError("Provide an API-format graph with 1â€“500 nodes")
            if any(
                not isinstance(node, dict)
                or not isinstance(node.get("class_type"), str)
                or not node["class_type"].strip()
                or not isinstance(node.get("inputs"), dict)
                for node in graph.values()
            ):
                raise ProviderError("Each graph node must have a class_type and an inputs object")
            bindings = args.get("asset_bindings", {})
            if not isinstance(bindings, dict) or len(bindings) > 4:
                raise ProviderError("asset_bindings must map up to four image slots to project asset IDs")
            if operation in {"prepare_workflow", "prepare_graph"}:
                from .recipe_adaptation import adapt_references, apply_canvas, optional_qwen_loader, output_graph
                is_package = operation == "prepare_workflow" and bool(recipe_manifest.get("block_party"))
                if self.message_id and args.get("output_kind", "image") == "image" and not is_package:
                    from .database import Message, Conversation
                    from .local_render import message_render_request
                    with self.session_factory() as session:
                        source = session.get(Message, self.message_id)
                        conversation = session.get(Conversation, source.conversation_id) if source else None
                        if source and conversation and conversation.project_id == self.project_id:
                            apply_canvas(graph, message_render_request(session, source))
                retained_bindings = {**{slot: "inherited-project-reference" for slot in trusted_saved_images}, **bindings}
                active = output_graph(graph)
                optional = {key: node for key, node in active.items() if node.get("class_type") in {"LoadImage", "LoadImageMask"}
                            and f"{key}.image" not in retained_bindings and optional_qwen_loader(active, key)}
                schemas = self.provider.live_node_schemas({key: node for key, node in active.items()
                    if node.get("class_type") == "TextEncodeQwenImage21"}) if optional else {}
                if not is_package:
                    graph = adapt_references(graph, retained_bindings, schemas)
            unbound_saved_images = [
                f"{node_id}.image"
                for node_id, node in graph.items()
                if node.get("class_type") in {"LoadImage", "LoadImageMask"}
                and isinstance(node.get("inputs", {}).get("image"), str)
                and f"{node_id}.image" not in bindings
                and trusted_saved_images.get(f"{node_id}.image") != node["inputs"]["image"]
            ]
            if operation in {"prepare_workflow", "prepare_graph"} and unbound_saved_images:
                raise ProviderError(
                    "Unbound template image inputs: "
                    + ", ".join(unbound_saved_images)
                    + ". Saved example images cannot enter a project draft; bind active-project assets "
                    "or remove the unused image loaders before preparing it."
                )
            unbound_templates = [
                f"{node_id}.{field}"
                for node_id, node in graph.items()
                for field, value in node.get("inputs", {}).items()
                if node.get("class_type") in {"LoadImage", "LoadImageMask"}
                and field == "image"
                and isinstance(value, str)
                and value.startswith("__")
                and value.endswith("__")
                and f"{node_id}.{field}" not in bindings
            ]
            if unbound_templates:
                raise ProviderError(
                    "Unbound template image inputs: " + ", ".join(unbound_templates) + ". "
                    "Bind each requested project image with asset_bindings before queueing."
                )
            if bindings and args.get("output_kind") == "video" and not self.source_asset_ids:
                unbound = [f"{node_id}.image" for node_id, node in graph.items()
                           if node["class_type"] in {"LoadImage", "LoadImageMask"} and "image" in node["inputs"] and f"{node_id}.image" not in bindings]
                if unbound:
                    raise ProviderError("Unbound template image inputs: " + ", ".join(unbound) + ". Bind requested project images or remove unused optional reference inputs and loaders from a graph copy.")
            for slot, asset_id in bindings.items():
                node_id, field = resolve_graph_slot(graph, slot)
                if graph[node_id]["class_type"] not in {"LoadImage", "LoadImageMask"} or field != "image":
                    raise ProviderError("Bind project images only to inspected image loader slots")
                with self.session_factory() as session:
                    asset = session.get(Asset, asset_id) if isinstance(asset_id, str) else None
                    if not asset or asset.project_id != self.project_id or asset.kind != "image":
                        raise ProviderError("Image binding must reference an image in this project")
                uploaded = self._call("upload_asset", {"asset_id": asset_id}, timeout)["upload"]
                name = uploaded.get("name")
                if not isinstance(name, str) or not name or "/" in name or "\\" in name:
                    raise ProviderError("ComfyUI upload did not return a usable image filename")
                subfolder = uploaded.get("subfolder", "")
                if not isinstance(subfolder, str) or subfolder.startswith(("/", "\\")) or ":" in subfolder or ".." in Path(subfolder).parts:
                    raise ProviderError("ComfyUI returned an invalid image subfolder")
                graph[node_id]["inputs"][field] = f"{subfolder}/{name}" if subfolder else name
            graph_file = directory / "graph.json"
            if operation in {"prepare_workflow", "prepare_graph"}:
                from .generation_identity import prepare_seeds
                if operation == "prepare_workflow" and recipe_manifest.get("block_party"):
                    from .block_party import prepare_declared_seeds
                    prepare_declared_seeds(graph, recipe_manifest, args.get("seed_mode", "randomize"), args.get("overrides", {}))
                else:
                    prepare_seeds(graph, args.get("seed_mode", "randomize"))
            # Uploads above are synchronous. Check actual image availability
            # before presenting a runnable draft, then recheck at execution.
            self.on_activity("validate_graph", "running")
            graph = validate_graph(graph, comfy_base_url=self.settings.comfyui_base_url)
            graph_file.write_text(json.dumps(graph), encoding="utf-8")
            validation = self.provider.validate_api_graph(graph_file, graph, timeout)
            if validation.get("valid") is not True or validation.get("errors"):
                self.on_activity("validate_graph", "failed")
                return {"error": "Workflow validation failed", "validation": validation}
            self.on_activity("validate_graph", "complete")
            if operation == "validate_graph":
                return {"validation": validation}
            return self._register(graph, args, root, validation)

    def _register(self, graph, args, root, validation):
        self.source_asset_ids = list(dict.fromkeys(self.source_asset_ids))
        prefixes = [f"{node_id}.filename_prefix" for node_id, node in graph.items() if isinstance(node, dict) and "filename_prefix" in node.get("inputs", {})]
        if not prefixes:
            raise ProviderError("Add a saved output node with a filename_prefix input before preparing this graph")
        identity = json.dumps({"graph": graph, "name": args.get("name"), "output_kind": args.get("output_kind", "image"), "capability": args.get("capability", "text-to-image"), "project_id": self.project_id, "source_asset_ids": self.source_asset_ids, "brief_id": args.get("brief_id"), "task_id": self.message_id, "prompt_bindings": args.get("prompt_bindings", {})}, sort_keys=True)
        workflow_id = "assistant-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
        inputs = []
        for node_id, node in graph.items():
            for key, value in node.get("inputs", {}).items():
                if key == "filename_prefix" or not isinstance(value, (str, int, float, bool)):
                    continue
                inputs.append({"key": f"input_{len(inputs)}", "type": "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "number" if isinstance(value, float) else "string", "required": False, "default": value if value != "" else None, "description": f"{node.get('class_type')} \u00b7 {node_id}.{key}", "maps_to": {"slot": f"{node_id}.{key}"}})
        target = root / f"{workflow_id}.json"
        contract = WorkflowContract.model_validate({
            "id": workflow_id, "name": self._text(args, "name"), "version": "1", "capability": args.get("capability", "text-to-image"),
            "execution_provider": "local-comfyui", "workflow_reference": str(target), "required_inputs": inputs,
            "output": {"kind": args.get("output_kind", "image"), "count": len(prefixes)},
            "runtime_mapping": {"filename_prefix_slot": prefixes[0], "api_format": True}, "requires_approval": True,
            "source_asset_ids": self.source_asset_ids,
            "project_id": self.project_id,
            "origin_workflow_id": args.get("workflow_id") if isinstance(args.get("workflow_id"), str) else None,
            "generation_brief_id": args.get("brief_id"), "generation_task_id": self.message_id,
            "prompt_bindings": args.get("prompt_bindings", {}),
        })
        if not target.exists():
            target.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        try:
            self.registry.get(workflow_id)
        except KeyError:
            self.registry.add(contract)
        register_workflows(self.session_factory, self.registry)
        if contract.generation_brief_id and self.message_id and self.session_factory:
            from .database import Message
            with self.session_factory.begin() as session:
                source = session.get(Message, self.message_id)
                if source:
                    drafts = {**source.metadata_json.get("shot_workflows", {}), contract.generation_brief_id: workflow_id}
                    source.metadata_json = {**source.metadata_json, "shot_workflows": drafts}
        # Preparation is always a draft. The planner decides whether to stop here or
        # immediately queue it: standing local permission removes the second approval
        # only when the user's current message explicitly asks to render now.
        return {"workflow_id": workflow_id, "name": contract.name, "node_count": len(graph), "validation": validation,
                "state": "draft", "requires_approval": True,
                "instruction": "Draft prepared. If the current user explicitly asked to render/generate now and project local rendering is enabled, call queue_local_render with this workflow_id. Otherwise return the workflow_id and generation_prompt for review; nothing is queued."}
