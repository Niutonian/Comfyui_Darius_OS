from __future__ import annotations

import json
import uuid
import threading
import time
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update, text
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .bfl_catalog import estimate as estimate_bfl
from .database import (
    ActionPlan,
    ActionPlanTransition,
    Asset,
    Conversation,
    GenerationRecord,
    Job,
    Message,
    Project,
    ProjectEvent,
    Scene,
    Shot,
    Timeline,
    TimelineVersion,
    WorkflowDefinitionRecord,
    utcnow,
)
from .media import ingest_generated
from .media_processing import generate_derivatives
from .providers import ComfyMcpProvider, GenerationProvider
from .timeline_ops import FfmpegTimelineRenderer, TimelineValidationError, validate_tracks, validate_tracks_for_render
from .workflows import WorkflowRegistry
from .generation_identity import input_seeds, output_name
from .chat_labels import output_label


class RequestError(ValueError):
    pass


def new_id() -> str:
    return str(uuid.uuid4())


def _check_workflow_source_assets(session: Session, contract, project_id: str, *, request_error: bool) -> None:
    """Ensure referenced project media still exists before queueing or execution."""
    error_type = RequestError if request_error else RuntimeError
    from .assistant_context import workflow_available
    if not workflow_available(session, project_id, contract):
        raise error_type("workflow does not belong to this project")
    for asset_id in contract.source_asset_ids:
        asset = session.get(Asset, asset_id)
        if not asset or asset.project_id != project_id:
            raise error_type(f"workflow source asset {asset_id} no longer belongs to this project")
        if asset.kind == "image" and not Path(asset.path).resolve().is_file():
            raise error_type(f"workflow source asset {asset_id} is missing from managed storage")


def update_agent_task(session, job):
    message_id = job.input_payload.get("local_render_message_id")
    source = session.get(Message, message_id) if message_id else None
    conversation = session.get(Conversation, source.conversation_id) if source else None
    if source and conversation and conversation.project_id == job.project_id and source.metadata_json.get("task", {}).get("engine") == "langgraph":
        ids = list(dict.fromkeys([*source.metadata_json.get("local_render_job_ids", []), job.id]))
        related = [item for key in ids if (item := session.get(Job, key))
                   and item.project_id == job.project_id and item.input_payload.get("local_render_message_id") == source.id]
        states = {item.status for item in related}
        from .task_lifecycle import render_state
        state = render_state(states)
        task = {**source.metadata_json["task"], "state": state, "step": "render",
                "job_id": related[0].id, "job_ids": [item.id for item in related],
                "jobs": [{"job_id": item.id, "status": item.status, "name": item.display_name} for item in related],
                "output_asset_ids": list(dict.fromkeys(key for item in related for key in item.output_asset_ids))}
        source.metadata_json = {**source.metadata_json, "task": task}
        for reply in session.scalars(select(Message).where(Message.conversation_id == source.conversation_id, Message.role == "assistant", Message.metadata_json["reply_to"].as_string() == source.id)):
            reply.metadata_json = {**reply.metadata_json, "task": task}
        add_event(session, job.project_id, "assistant.task_updated", "message", source.id, task)


def add_event(
    session: Session,
    project_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
) -> ProjectEvent:
    event = ProjectEvent(
        id=new_id(),
        project_id=project_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload or {},
    )
    session.add(event)
    return event


def register_workflows(session_factory: sessionmaker, registry: WorkflowRegistry) -> None:
    with session_factory.begin() as session:
        for contract in registry.enabled(include_internal=True):
            record = session.get(WorkflowDefinitionRecord, contract.id)
            values = {
                "name": contract.name,
                "version": contract.version,
                "capability": contract.capability,
                "execution_provider": contract.execution_provider,
                "contract": registry.serialized(contract),
                "enabled": contract.enabled,
                "updated_at": utcnow(),
            }
            if record is None:
                session.add(WorkflowDefinitionRecord(id=contract.id, **values))
            else:
                for key, value in values.items():
                    setattr(record, key, value)


def create_project(session_factory: sessionmaker, name: str, description: str = "", **values) -> Project:  # noqa: ANN003
    project = Project(id=new_id(), name=name.strip(), description=description, **values)
    with session_factory.begin() as session:
        session.add(project)
        add_event(session, project.id, "project.created", "project", project.id, {"name": project.name})
    return project


def enqueue_request(
    session_factory: sessionmaker,
    registry: WorkflowRegistry,
    project_id: str,
    workflow_id: str,
    request_text: str,
    inputs: dict[str, Any],
    approved: bool,
    *, expected_graph_digest: str | None = None, _session: Session | None = None, allow_internal: bool = False,
) -> Job:
    try:
        contract = registry.get(workflow_id)
    except KeyError as exc:
        raise RequestError(str(exc)) from exc
    if not contract.enabled:
        raise RequestError("workflow is disabled")
    if contract.internal_only and not allow_internal:
        raise RequestError("This workflow belongs to a saved Canvas revision. Generate it from Canvas instead.")
    if contract.requires_approval and not approved:
        raise RequestError("workflow requires explicit approval")
    try:
        normalized = contract.validate_inputs(inputs)
    except ValueError as exc:
        raise RequestError(str(exc)) from exc
    if expected_graph_digest:
        from .render_preview import preview_contract
        try:
            current = preview_contract(contract, normalized, request_text)
        except (OSError, ValueError) as exc:
            raise RequestError("The reviewed workflow is unavailable. Create a fresh action plan.") from exc
        if current["graph_digest"] != expected_graph_digest:
            raise RequestError("The workflow changed since review. Create a fresh action plan before approving.")
    if contract.runtime_mapping.api_format:
        try:
            graph = json.loads(Path(contract.workflow_reference).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RequestError("workflow graph is unavailable; inspect or repair the workflow before queueing") from exc
        from .comfy_preflight import validate_capability_graph
        try:
            validate_capability_graph(graph, contract.capability)
        except Exception as exc:
            raise RequestError(str(exc)) from exc
    job = Job(
        id=new_id(),
        project_id=project_id,
        provider=contract.execution_provider,
        status="queued",
        progress=0.0,
        status_message="Approved and queued",
        input_payload={"workflow_id": workflow_id, "inputs": normalized, "approved": approved,
                       "approval_source": "manual_review" if approved else None,
                       "render_name": request_text},
        output_asset_ids=[],
    )
    if expected_graph_digest:
        job.input_payload = {**job.input_payload, "reviewed_graph_digest": expected_graph_digest}
    with (nullcontext(_session) if _session is not None else session_factory.begin()) as session:
        if session.get(Project, project_id) is None:
            raise RequestError("project does not exist")
        _check_workflow_source_assets(session, contract, project_id, request_error=True)
        if contract.execution_provider == "bfl":
            from .bfl_catalog import resolve_media, reference_ids, estimate
            try:
                resolve_media(session, project_id, normalized)
            except ValueError as exc:
                raise RequestError(str(exc)) from exc
        from .shot_board import production_context
        context = production_context(session, project_id)
        if context:
            job.input_payload = {**job.input_payload, "production_context": context}
        session.add(job)
        session.flush()
        session.add(
            GenerationRecord(
                id=new_id(),
                job_id=job.id,
                workflow_definition_id=workflow_id,
                prompt=normalized.get("prompt", request_text) if contract.execution_provider == "bfl" else request_text,
                seed=next(iter(input_seeds(contract, normalized).values()), None),
                parameters=normalized,
                source_asset_ids=list(dict.fromkeys([*contract.source_asset_ids, *(reference_ids(normalized) if contract.execution_provider == "bfl" else [])])),
                provider_response_metadata={},
                estimated_cost=estimate(contract.id, normalized) if contract.id.startswith("bfl-flux-3-") else contract.estimated_cost,
            )
        )
        add_event(
            session,
            project_id,
            "generation.queued",
            "job",
            job.id,
            {"workflow_id": workflow_id, "approved": approved},
        )
    return job


def create_action_plan(
    session_factory: sessionmaker,
    registry: WorkflowRegistry,
    project_id: str,
    workflow_id: str,
    request_text: str,
    inputs: dict[str, Any],
    conversation_id: str | None = None,
    source_message_id: str | None = None,
) -> ActionPlan:
    if conversation_id or source_message_id:
        raise RequestError("This conversation develops prompts. Use in board to apply text, then Generate on the board.")
    try:
        contract = registry.get(workflow_id)
        if contract.generation_task_id:
            raise RequestError("This conversation workflow proposal is retired. Apply its prompt to a board instead.")
        normalized = contract.validate_inputs(inputs)
    except (KeyError, ValueError) as exc:
        raise RequestError(str(exc)) from exc
    from .render_preview import preview_contract
    try:
        render_preview = preview_contract(contract, normalized, request_text)
    except (OSError, ValueError) as exc:
        raise RequestError("Could not inspect the final workflow inputs.") from exc
    if render_preview["blocked"]:
        raise RequestError(render_preview["warnings"][0])
    plan = ActionPlan(
        id=new_id(),
        project_id=project_id,
        conversation_id=conversation_id,
        workflow_definition_id=workflow_id,
        request_text=request_text,
        provider=contract.execution_provider,
        inputs=normalized,
        expected_output={**contract.output.model_dump(), "render_preview": render_preview},
        estimated_cost=estimate_bfl(contract.id, normalized) if contract.id.startswith("bfl-flux-3-") else contract.estimated_cost,
        state="proposed",
    )
    with session_factory.begin() as session:
        if session.get(Project, project_id) is None:
            raise RequestError("project does not exist")
        source_id = source_message_id or contract.generation_task_id
        if source_id:
            source = session.get(Message, source_id)
            conversation = session.get(Conversation, source.conversation_id) if source else None
            if not source or source.role != "user" or not conversation or conversation.project_id != project_id:
                raise RequestError("The source message does not belong to this project.")
            if conversation_id and conversation_id != conversation.id:
                raise RequestError("The source message does not belong to this conversation.")
            plan.conversation_id = conversation.id
            plan.expected_output = {**plan.expected_output, "source_message_id": source.id}
        elif conversation_id:
            conversation = session.get(Conversation, conversation_id)
            if not conversation or conversation.project_id != project_id:
                raise RequestError("The conversation does not belong to this project.")
        session.add(plan)
        _check_workflow_source_assets(session, contract, project_id, request_error=True)
        if contract.execution_provider == "bfl":
            from .bfl_catalog import resolve_media
            try:
                resolve_media(session, project_id, normalized)
            except ValueError as exc:
                raise RequestError(str(exc)) from exc
        session.flush()
        session.add(ActionPlanTransition(id=new_id(), action_plan_id=plan.id, from_state=None, to_state="proposed"))
        add_event(session, project_id, "action_plan.proposed", "action_plan", plan.id, {"workflow_id": workflow_id})
    return plan


def approve_action_plan(
    session_factory: sessionmaker, registry: WorkflowRegistry, plan_id: str
) -> ActionPlan:
    # Claim the approval and create its job in ONE transaction. A retry cannot
    # enqueue a second paid/render request before noticing a changed plan.
    with session_factory.begin() as session:
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        plan = session.scalar(select(ActionPlan).where(ActionPlan.id == plan_id).with_for_update())
        if plan is None:
            raise RequestError("action plan does not exist")
        if plan.job_id and plan.state not in {"cancelled", "proposed"}:
            job = session.get(Job, plan.job_id)
            if job and job.project_id == plan.project_id:
                return plan
        if plan.conversation_id or plan.expected_output.get("source_message_id"):
            raise RequestError("Unsubmitted chat proposals no longer run here. Apply the prompt to a board and use its Generate control.")
        if plan.state != "proposed":
            raise RequestError(f"action plan cannot be approved from {plan.state}")
        values = (plan.project_id, plan.workflow_definition_id, plan.request_text, dict(plan.inputs))
        graph_digest = (plan.expected_output.get("render_preview") or {}).get("graph_digest")
        source_id = plan.expected_output.get("source_message_id")
        source = session.get(Message, source_id) if source_id else None
        if source_id:
            conversation = session.get(Conversation, source.conversation_id) if source else None
            if not source or source.role != "user" or not conversation or conversation.project_id != plan.project_id or conversation.id != plan.conversation_id:
                raise RequestError("The reviewed source message is no longer available in this project.")
        job = enqueue_request(session_factory, registry, *values, approved=True,
                              expected_graph_digest=graph_digest, _session=session)
        if source:
            job.input_payload = {**job.input_payload, "local_render_message_id": source.id}
            ids = list(dict.fromkeys([*source.metadata_json.get("local_render_job_ids", []),
                *([source.metadata_json["local_render_job_id"]] if source.metadata_json.get("local_render_job_id") else []), job.id]))
            source.metadata_json = {**source.metadata_json, "local_render_job_id": ids[0], "local_render_job_ids": ids,
                "task": {**source.metadata_json.get("task", {}), "engine": "langgraph", "state": "queued", "step": "render", "job_id": job.id}}
            for reply in session.scalars(select(Message).where(Message.conversation_id == source.conversation_id, Message.role == "assistant")):
                if reply.metadata_json.get("reply_to") == source.id:
                    metadata = {**reply.metadata_json, "job_id": job.id, "job_ids": ids, "reviewed_generation": True}
                    if isinstance(metadata.get("generation_drafts"), list):
                        metadata["generation_drafts"] = [
                            {**draft, "job_id": job.id} if isinstance(draft, dict) and draft.get("workflow_id") == plan.workflow_definition_id else draft
                            for draft in metadata["generation_drafts"]]
                    reply.metadata_json = metadata
            add_event(session, plan.project_id, "assistant.task_updated", "message", source.id, source.metadata_json["task"])
        now = utcnow()
        session.add(ActionPlanTransition(
            id=new_id(), action_plan_id=plan.id, from_state="proposed", to_state="approved",
            created_at=now,
        ))
        session.add(ActionPlanTransition(
            id=new_id(), action_plan_id=plan.id, from_state="approved", to_state="queued",
            created_at=now + timedelta(microseconds=1),
        ))
        plan.state = "queued"
        plan.job_id = job.id
        plan.updated_at = utcnow()
        add_event(session, plan.project_id, "action_plan.approved", "action_plan", plan.id, {"job_id": job.id})
    return plan


def cancel_job(session_factory: sessionmaker, job_id: str) -> Job:
    with session_factory.begin() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise RequestError("job does not exist")
        if job.status == "queued":
            job.status = "cancelled"
            job.status_message = "Cancelled before execution"
            job.completed_at = utcnow()
            job.cancellation_requested = True
        elif job.status == "running":
            job.status = "cancelling"
            job.status_message = "Cancelled locally; BFL's paid request may continue" if job.provider == "bfl" else "Cancellation requested"
            job.cancellation_requested = True
        elif job.status == "cancelling":
            return job
        else:
            raise RequestError(f"job cannot be cancelled from {job.status}")
        add_event(session, job.project_id, "job.cancellation_requested", "job", job.id, {"status": job.status})
        update_agent_task(session, job)
        return job


def cancel_action_plan(session_factory: sessionmaker, plan_id: str) -> ActionPlan:
    with session_factory() as session:
        plan = session.get(ActionPlan, plan_id)
        if plan is None:
            raise RequestError("action plan does not exist")
        if plan.state not in {"proposed", "approved", "queued", "running"}:
            raise RequestError(f"action plan cannot be cancelled from {plan.state}")
        old_state, job_id = plan.state, plan.job_id
    if job_id:
        cancel_job(session_factory, job_id)
    with session_factory.begin() as session:
        plan = session.get(ActionPlan, plan_id)
        if plan is None:
            raise RequestError("action plan does not exist")
        plan.state = "cancelled"
        plan.updated_at = utcnow()
        session.add(ActionPlanTransition(id=new_id(), action_plan_id=plan.id, from_state=old_state, to_state="cancelled"))
        add_event(session, plan.project_id, "action_plan.cancelled", "action_plan", plan.id, {"job_id": job_id})
        return plan


def retry_job(session_factory: sessionmaker, job_id: str) -> Job:
    with session_factory.begin() as session:
        original = session.get(Job, job_id)
        if original is None:
            raise RequestError("job does not exist")
        if original.input_payload.get("canvas_generation_id"):
            raise RequestError("Regenerate this composition from Canvas so its revision, seed and version history stay linked")
        if original.status not in {"failed", "cancelled"}:
            raise RequestError(f"job cannot be retried from {original.status}")
        generation = session.scalar(select(GenerationRecord).where(GenerationRecord.job_id == job_id))
        if generation is None and original.job_type != "timeline_render":
            raise RequestError("job has no generation record")
        retried = Job(
            id=new_id(), project_id=original.project_id, job_type=original.job_type,
            provider=original.provider, status="queued", progress=0.0,
            status_message="Queued as retry", input_payload={key: value for key, value in original.input_payload.items() if key != "timeline_worker_start"},
            output_asset_ids=[], retry_of_job_id=original.id,
        )
        session.add(retried)
        session.flush()
        if generation is not None:
            session.add(GenerationRecord(
                id=new_id(), job_id=retried.id,
                workflow_definition_id=generation.workflow_definition_id,
                prompt=generation.prompt, negative_prompt=generation.negative_prompt,
                seed=generation.seed, model=generation.model,
                parameters=dict(generation.parameters), source_asset_ids=list(generation.source_asset_ids),
                provider_response_metadata={}, estimated_cost=generation.estimated_cost,
            ))
        add_event(session, original.project_id, "job.retried", "job", retried.id, {"retry_of_job_id": original.id})
        return retried


def create_media_derivatives(
    session_factory: sessionmaker,
    settings: Settings,
    asset_id: str,
    *, thumbnail_only: bool = False,
) -> tuple[list[Asset], list[str]]:
    with session_factory() as session:
        source = session.get(Asset, asset_id)
        if source is None:
            raise RequestError("asset does not exist")
        source_values = {
            "id": source.id, "project_id": source.project_id, "path": source.path,
            "kind": source.kind, "scene_id": source.scene_id, "shot_id": source.shot_id,
            "approval_state": source.approval_state,
        }
    args = (Path(source_values["path"]), source_values["kind"], settings, source_values["project_id"])
    outcomes = generate_derivatives(*args, thumbnail_only=True) if thumbnail_only else generate_derivatives(*args)
    derivatives: list[Asset] = []
    warnings: list[str] = []
    for outcome in outcomes:
        if outcome.media is None:
            warnings.append(f"{outcome.derivative_type}: {outcome.error or 'unavailable'}")
            continue
        media = outcome.media
        derivatives.append(Asset(
            id=new_id(), project_id=source_values["project_id"], kind=media.kind,
            role="derivative", path=str(media.path), content_hash=media.content_hash,
            mime_type=media.mime_type, width=media.width, height=media.height,
            duration=media.duration, fps=media.fps, sample_rate=media.sample_rate,
            parent_asset_ids=[source_values["id"]], scene_id=source_values["scene_id"],
            shot_id=source_values["shot_id"], provider="ffmpeg", workflow_run_id=None,
            approval_state=source_values["approval_state"],
            metadata_json={**media.metadata, "derivative_type": outcome.derivative_type, "source_asset_id": source_values["id"]},
        ))
    try:
        with session_factory.begin() as session:
            for derivative in derivatives:
                session.add(derivative)
                add_event(session, derivative.project_id, "asset.derivative_created", "asset", derivative.id, {
                    "source_asset_id": source_values["id"],
                    "derivative_type": derivative.metadata_json["derivative_type"],
                })
            add_event(session, source_values["project_id"], "asset.derivatives_processed", "asset", source_values["id"], {
                "derivative_asset_ids": [item.id for item in derivatives], "warnings": warnings,
            })
    except Exception:
        for derivative in derivatives:
            Path(derivative.path).unlink(missing_ok=True)
        raise
    return derivatives, warnings


_thumbnail_locks = [threading.RLock() for _ in range(64)]


def ensure_media_thumbnail(session_factory, settings, asset_id):
    """Reuse an immutable asset's thumbnail across refreshes/devices, without new proxies."""
    with _thumbnail_locks[hash(asset_id) % len(_thumbnail_locks)]:
        with session_factory() as session:
            source = session.get(Asset, asset_id)
            if not source:
                raise RequestError("asset does not exist")
            candidates = session.scalars(select(Asset).where(Asset.project_id == source.project_id, Asset.role == "derivative",
                Asset.metadata_json["source_asset_id"].as_string() == source.id,
                Asset.metadata_json["derivative_type"].as_string() == "thumbnail")).all()
            cached = next((asset for asset in candidates if Path(asset.path).is_file()), None)
            if cached:
                return [cached], []
        return create_media_derivatives(session_factory, settings, asset_id, thumbnail_only=True)


def queue_timeline_render(
    session_factory: sessionmaker,
    timeline_id: str,
    version_id: str,
    approved: bool,
) -> Job:
    if not approved:
        raise RequestError("timeline render requires explicit approval")
    with session_factory.begin() as session:
        timeline = session.get(Timeline, timeline_id)
        version = session.get(TimelineVersion, version_id)
        if timeline is None:
            raise RequestError("timeline does not exist")
        if version is None or version.timeline_id != timeline.id:
            raise RequestError("timeline version does not exist")
        if version.state != "accepted":
            raise RequestError("only an accepted timeline version can be rendered")
        try:
            validate_tracks(session, timeline, list(version.tracks))
            validate_tracks_for_render(list(version.tracks))
        except TimelineValidationError as exc:
            raise RequestError(str(exc)) from exc
        job = Job(
            id=new_id(), project_id=timeline.project_id, job_type="timeline_render",
            provider="ffmpeg", status="queued", progress=0.0,
            status_message="Approved timeline render queued",
            input_payload={"timeline_id": timeline.id, "timeline_version_id": version.id, "approved": True},
            output_asset_ids=[],
        )
        session.add(job)
        add_event(session, timeline.project_id, "timeline.render_queued", "job", job.id, {
            "timeline_id": timeline.id, "timeline_version_id": version.id,
        })
        return job


def create_timeline_version(
    session_factory: sessionmaker,
    timeline_id: str,
    tracks: list[dict[str, Any]],
    state: str,
    edit_summary: str,
    created_by: str,
) -> TimelineVersion:
    with session_factory.begin() as session:
        timeline = session.get(Timeline, timeline_id)
        if timeline is None:
            raise RequestError("timeline does not exist")
        try:
            validate_tracks(session, timeline, tracks)
        except TimelineValidationError as exc:
            raise RequestError(str(exc)) from exc
        version_number = (session.scalar(select(func.max(TimelineVersion.version_number)).where(TimelineVersion.timeline_id == timeline_id)) or 0) + 1
        version = TimelineVersion(
            id=new_id(), timeline_id=timeline_id, version_number=version_number,
            state=state, tracks=tracks, edit_summary=edit_summary, created_by=created_by,
        )
        session.add(version)
        timeline.updated_at = utcnow()
        add_event(session, timeline.project_id, "timeline.version_created", "timeline_version", version.id, {"timeline_id": timeline.id, "version_number": version_number, "state": state})
        return version


def propose_timeline(session_factory: sessionmaker, timeline_id: str, scene_id: str | None = None) -> TimelineVersion:
    with session_factory() as session:
        timeline = session.get(Timeline, timeline_id)
        if timeline is None:
            raise RequestError("timeline does not exist")
        selected_scene = scene_id or timeline.scene_id
        query = select(Shot).join(Scene, Shot.scene_id == Scene.id).where(Scene.project_id == timeline.project_id)
        if selected_scene:
            query = query.where(Shot.scene_id == selected_scene)
        shots = list(session.scalars(query.order_by(Scene.number, Shot.number)))
        assets = {asset.id: asset for asset in session.scalars(select(Asset).where(Asset.project_id == timeline.project_id))}
    video_clips: list[dict[str, Any]] = []
    dialogue_clips: list[dict[str, Any]] = []
    cursor = 0.0
    for shot in shots:
        if not shot.selected_asset_id or shot.selected_asset_id not in assets:
            continue
        asset = assets[shot.selected_asset_id]
        duration = min(shot.duration_target, asset.duration) if asset.duration else shot.duration_target
        duration = round(max(duration, 0.001), 3)
        video_clips.append({
            "id": f"shot-{shot.id}", "source_asset_id": asset.id,
            "source_in": 0.0, "source_out": duration,
            "timeline_in": round(cursor, 3), "timeline_out": round(cursor + duration, 3),
            "reason": "dialogue" if shot.dialogue else "action", "confidence": 1.0,
            "shot_id": shot.id,
        })
        if shot.dialogue:
            dialogue_clips.append({
                "id": f"dialogue-{shot.id}", "shot_id": shot.id, "text": shot.dialogue,
                "timeline_in": round(cursor, 3), "timeline_out": round(cursor + duration, 3),
                "reason": "dialogue", "confidence": 1.0,
            })
        cursor += duration
    tracks = [{"kind": "video", "clips": video_clips}, {"kind": "dialogue", "clips": dialogue_clips}]
    return create_timeline_version(
        session_factory, timeline_id, tracks, "proposed",
        f"Deterministic assembly of {len(video_clips)} selected shots.", "darius",
    )


class JobWorker:
    def __init__(
        self, session_factory: sessionmaker, registry: WorkflowRegistry, settings: Settings,
        provider: GenerationProvider, timeline_renderer=None,
    ):  # noqa: ANN001
        self.session_factory = session_factory
        self.registry = registry
        self.settings = settings
        self.provider = provider
        self.timeline_renderer = timeline_renderer or FfmpegTimelineRenderer()

    def recover_abandoned(self, older_than: timedelta = timedelta(minutes=5)) -> int:
        from .job_recovery import recover_abandoned_local_jobs
        recovered_local = recover_abandoned_local_jobs(self.session_factory, self.settings, older_than=older_than)
        cutoff = utcnow() - older_than
        # Local generations must never bypass the queue check or be replayed by
        # the persistent worker's legacy recovery path.
        legacy_job = (Job.provider != "local-comfyui") | (Job.job_type != "generation")
        with self.session_factory.begin() as session:
            requeued = session.execute(
                update(Job).where(legacy_job, Job.status == "running").where((Job.heartbeat_at.is_(None)) | (Job.heartbeat_at < cutoff)).values(status="queued", status_message="Recovered after worker restart")
            ).rowcount
            cancelled = session.execute(
                update(Job).where(legacy_job, Job.status == "cancelling").where((Job.heartbeat_at.is_(None)) | (Job.heartbeat_at < cutoff)).values(
                    status="cancelled", status_message="Cancellation completed during restart recovery", completed_at=utcnow()
                )
            ).rowcount
            return len(recovered_local) + requeued + cancelled

    def claim_next(self, only_job_id: str | None = None) -> str | None:
        with self.session_factory.begin() as session:
            query = select(Job.id).where(Job.status == "queued")
            if only_job_id is not None:
                query = query.where(Job.id == only_job_id)
            job_id = session.scalar(query.order_by(Job.created_at).limit(1))
            if job_id is None:
                return None
            now = utcnow()
            result = session.execute(
                update(Job).where(Job.id == job_id, Job.status == "queued").values(
                    status="running", progress=0.05, status_message="Claimed by worker",
                    started_at=now, heartbeat_at=now, attempt_count=Job.attempt_count + 1,
                )
            )
            if result.rowcount == 1:
                plan = session.scalar(select(ActionPlan).where(ActionPlan.job_id == job_id))
                if plan:
                    session.add(ActionPlanTransition(id=new_id(), action_plan_id=plan.id, from_state=plan.state, to_state="running"))
                    plan.state = "running"
                    plan.updated_at = now
                update_agent_task(session, session.get(Job, job_id))
                return job_id
            return None

    def run_once(self, only_job_id: str | None = None) -> str | None:
        # Capacity is acquired before claiming: waiting work stays Queued in
        # both the board badge and the global tray, including other projects.
        with self.session_factory.begin() as session:
            query = select(Job).where(Job.status == "queued")
            if only_job_id:
                query = query.where(Job.id == only_job_id)
            candidate = session.scalar(query.order_by(Job.created_at, Job.id).limit(1))
            local = candidate and candidate.provider == "local-comfyui" and candidate.job_type == "generation"
            if local:
                if not candidate.input_payload.get("worker_ready"):
                    candidate.input_payload = {**candidate.input_payload, "worker_ready": True}
                    session.flush()
                oldest = session.scalar(select(Job.id).where(Job.status == "queued", Job.provider == "local-comfyui", Job.job_type == "generation",
                    (Job.input_payload["canvas_generation_id"].as_string().is_not(None)) | (Job.input_payload["worker_ready"].as_boolean() == True))
                    .order_by(Job.created_at, Job.id).limit(1))
                if oldest != candidate.id:
                    return None
        if not candidate:
            return None
        if not local:
            return self._run_claimed(candidate.id)
        from .gpu_handoff import gpu_lease
        try:
            with gpu_lease(self.settings, timeout=0):
                if isinstance(self.provider, ComfyMcpProvider):
                    import urllib.request
                    with urllib.request.urlopen(self.settings.comfyui_base_url.rstrip("/") + "/queue", timeout=3) as response:
                        queue = json.load(response)
                    if queue.get("queue_running") or queue.get("queue_pending"):
                        return None
                return self._run_claimed(candidate.id)
        except (TimeoutError, OSError):
            return None  # Busy/offline is queue state, not a failed generation.

    def _run_claimed(self, only_job_id: str | None = None) -> str | None:
        job_id = self.claim_next(only_job_id)
        if job_id is None:
            return None
        from .diagnostics import record
        record(self.settings, "worker", "info", "job_claimed", job_id=job_id)
        self._execute(job_id)
        with self.session_factory() as session:
            job = session.get(Job, job_id)
            if job:
                record(self.settings, "worker", "error" if job.status == "failed" else "info", "job_finished",
                       job_id=job_id, project_id=job.project_id, status=job.status, error=job.error_detail)
        return job_id

    def _execute(self, job_id: str) -> None:
        origin_workflow_id = None
        with self.session_factory.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            if job.cancellation_requested:
                job.status = "cancelled"
                job.status_message = "Cancelled before execution"
                job.completed_at = utcnow()
                self._finish_plan(session, job_id, "cancelled")
                return
            job_type = job.job_type
        if job_type == "timeline_render":
            self._execute_timeline_render(job_id)
            return
        with self.session_factory.begin() as session:
            job = session.get(Job, job_id)
            generation = session.scalar(select(GenerationRecord).where(GenerationRecord.job_id == job_id))
            if job is None or generation is None:
                return
            try:
                contract = self.registry.get(generation.workflow_definition_id)
            except (KeyError, OSError, ValueError) as exc:
                job.status = "failed"; job.status_message = "Workflow unavailable"
                job.error_code = "workflow_unavailable"; job.error_detail = str(exc)[:4000]; job.completed_at = utcnow()
                add_event(session, job.project_id, "generation.failed", "job", job.id, {"error_code": job.error_code})
                update_agent_task(session, job); self._finish_plan(session, job_id, "failed")
                return
            origin_workflow_id = contract.origin_workflow_id
            inputs, project_id = dict(generation.parameters), job.project_id
        try:
            with self.session_factory() as session:
                _check_workflow_source_assets(session, contract, project_id, request_error=False)
                current_job = session.get(Job, job_id)
                reviewed_digest = current_job.input_payload.get("reviewed_graph_digest")
                if reviewed_digest:
                    from .render_preview import preview_contract
                    if preview_contract(contract, inputs, generation.prompt)["graph_digest"] != reviewed_digest:
                        raise RequestError("The workflow changed after approval. Create a fresh reviewed action plan.")
                # A chat message ID links results back to their conversation; it
                # does not identify how execution was authorized. Reviewed chat
                # jobs carry it too. Standing permission is instead identified
                # by its immutable local_render_contract snapshot.
                payload = current_job.input_payload
                if payload.get("canvas_generation_id"):
                    from .canvas_moss import digest
                    if not contract.enabled or (payload.get("canvas_contract_digest") and digest(contract.model_dump(mode="json")) != payload["canvas_contract_digest"]):
                        raise RequestError("The Canvas workflow contract changed after approval; submit a fresh board snapshot")
                    if digest(json.loads(Path(contract.workflow_reference).read_text(encoding="utf-8"))) != payload.get("canvas_graph_digest"):
                        raise RequestError("The Canvas generation graph changed after approval; generate a new composition")
                    from .database import CanvasGenerationRecord
                    snapshot = session.get(CanvasGenerationRecord, payload["canvas_generation_id"])
                    if snapshot and contract.version in {"fibo-fast-experimental-v1", "fibo-fast-turbo-v2", "fibo-dev-v1"}:
                        from .canvas_fibo import local_model_fingerprints
                        captured = snapshot.provenance_json.get("availableModelFingerprints")
                        if captured and captured != local_model_fingerprints(self.settings, contract.version):
                            raise RequestError("FIBO model files or the runtime checkout changed after approval; submit a new composition snapshot")
                    if snapshot and contract.version.startswith("minimax-h3-"):
                        from .canvas_h3 import VideoConfig, validate_inputs
                        validate_inputs(session, project_id, VideoConfig.model_validate(snapshot.provenance_json["videoConfig"]))
                        from .canvas_h3 import model_fingerprints
                        captured = snapshot.provenance_json.get("availableModelFingerprints")
                        if captured and captured != model_fingerprints(self.settings, json.loads(Path(contract.workflow_reference).read_text(encoding="utf-8"))):
                            raise RequestError("MiniMax H3 model files changed after approval; submit a new video snapshot")
                    if snapshot and snapshot.provenance_json.get("imageConfig"):
                        from .canvas_images import Config, validate_inputs
                        from .canvas_h3 import model_fingerprints
                        validate_inputs(session, project_id, Config.model_validate(snapshot.provenance_json["imageConfig"]))
                        captured = snapshot.provenance_json.get("availableModelFingerprints")
                        if captured and captured != model_fingerprints(self.settings, json.loads(Path(contract.workflow_reference).read_text(encoding="utf-8"))):
                            raise RequestError("Image recipe model files changed after approval; submit a new snapshot")
                    if snapshot and snapshot.provenance_json.get("board"):
                        from .moss_workspace import BoardSettings, validate_references
                        frozen = snapshot.provenance_json["board"]
                        refs = BoardSettings.model_validate({k: frozen[k] for k in ("adapterVersion", "seed", "references")}).references
                        validate_references(session, project_id, frozen["boardId"], refs)
                        for ref in refs:
                            if not Path(session.get(Asset, ref.assetId).path).is_file():
                                raise RequestError("A pinned visual-note asset is missing; restore it or submit a new reference snapshot")
                manual_approval = (payload.get("approved") is True
                                   and "local_render_contract" not in payload
                                   and (payload.get("approval_source") == "manual_review"
                                        or bool(reviewed_digest)
                                        or "local_render_message_id" not in payload))
                if "local_render_contract" in current_job.input_payload:
                    from .local_render import authorized_contract
                    contract = authorized_contract(self.settings, session, current_job)
            # Keep long-running asynchronous providers alive in the job table
            # while they poll their remote/local queue. This prevents recovery
            # from mistaking a healthy ComfyUI render for a dead worker.
            heartbeat_stop = threading.Event()
            render_started = time.monotonic()

            def heartbeat() -> None:
                while not heartbeat_stop.wait(15):
                    with self.session_factory.begin() as session:
                        active = session.get(Job, job_id)
                        if active and active.status in {"running", "cancelling"}:
                            active.heartbeat_at = utcnow()
                        if active and active.status == "running":
                            elapsed = time.monotonic() - render_started
                            # ComfyUI history is only final after completion in
                            # this integration, so expose a bounded estimate
                            # instead of leaving the UI at 5% for the whole run.
                            estimated = min(0.85, 0.05 + elapsed / max(self.settings.comfy_job_timeout_seconds, 1) * 0.8)
                            if not active.input_payload.get("canvas_generation_id"):
                                active.progress = max(active.progress, estimated)
                            label = "BFL cloud" if contract.execution_provider == "bfl" else "ComfyUI"
                            active.status_message = f"Rendering with {label} Â· {int(elapsed)}s elapsed"

            heartbeat_thread = threading.Thread(target=heartbeat, name=f"darius-heartbeat-{job_id[:8]}", daemon=True)
            heartbeat_thread.start()
            try:
                if contract.execution_provider == "bfl":
                    if not manual_approval:
                        raise RequestError("BFL cloud generation requires explicit paid-workflow approval")
                    from .bfl_catalog import resolve_media
                    from .providers import BflProvider
                    with self.session_factory() as session:
                        remote_inputs = resolve_media(session, project_id, inputs, self.settings, encode=True)
                        submission = session.get(Job, job_id).input_payload.get("bfl_submission", {})
                    def save_submission(value):
                        with self.session_factory.begin() as session:
                            active = session.get(Job, job_id)
                            if active.cancellation_requested and not value.get("external_job_id"):
                                raise RequestError("Cancelled before BFL submission")
                            active.input_payload = {**active.input_payload, "bfl_submission": value}
                            active.external_job_id = value.get("external_job_id")
                    result = BflProvider(self.settings).execute(contract, remote_inputs, project_id, job_id,
                        submission=submission, on_submission=save_submission)
                elif isinstance(self.provider, ComfyMcpProvider):
                    # A persistent dispatcher follows the current selected local
                    # planner for GPU handoff without changing any saved settings.
                    from dataclasses import replace
                    from .database import LlmPreference
                    with self.session_factory() as session:
                        preference = session.get(LlmPreference, "default")
                    if preference:
                        self.provider.settings = replace(self.settings, llm_provider=preference.provider,
                            ollama_model=preference.model if preference.provider == "ollama" else self.settings.ollama_model)
                    result = self.provider.execute(contract, inputs, project_id, job_id,
                                                   manual_approval=manual_approval)
                else:
                    result = self.provider.execute(contract, inputs, project_id, job_id)
            finally:
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=2)
            asset_ids: list[str] = []
            with self.session_factory.begin() as session:
                generation = session.scalar(select(GenerationRecord).where(GenerationRecord.job_id == job_id))
                job = session.get(Job, job_id)
                if generation is None or job is None:
                    raise RuntimeError("job disappeared during execution")
                if job.status not in {"running", "cancelling"}:
                    return  # A recovered terminal receipt must not ingest late outputs.
                if job.cancellation_requested:
                    job.status = "cancelled"
                    job.progress = 0.0
                    job.status_message = "Cancelled locally; BFL may still bill the remote request" if job.provider == "bfl" else "Cancelled; provider outputs were not ingested"
                    job.completed_at = utcnow()
                    self._finish_plan(session, job_id, "cancelled")
                    return
                generation.provider_response_metadata = {**result.metadata, "mocked": result.mocked}
                job.external_job_id = result.external_job_id
                job.progress = 0.9
                job.status_message = "Ingesting outputs"
                job.heartbeat_at = utcnow()
                seeds = input_seeds(contract, inputs)
                generation.seed = next(iter(seeds.values()), generation.seed)
                for index, source in enumerate(result.outputs, 1):
                    media = ingest_generated(source, self.settings, project_id)
                    asset_id = new_id()
                    asset_ids.append(asset_id)
                    session.add(Asset(
                        id=asset_id, project_id=project_id, kind=media.kind, role="generation",
                        path=str(media.path), content_hash=media.content_hash, mime_type=media.mime_type,
                        width=media.width, height=media.height, duration=media.duration, fps=media.fps,
                        sample_rate=media.sample_rate, parent_asset_ids=list(generation.source_asset_ids),
                        provider=job.provider, workflow_run_id=job.id,
                        metadata_json={**media.metadata, **({key: value for key, value in result.metadata.items() if key.startswith("bfl_")} if job.provider == "bfl" else {}), "display_name": output_label(job.input_payload.get("render_name") or generation.prompt, media.kind, index), "generation_seeds": seeds, "prompt": generation.prompt, "mocked": result.mocked},
                    ))
                    add_event(session, project_id, "asset.created", "asset", asset_id, {"job_id": job.id, "content_hash": media.content_hash, "mocked": result.mocked})
                job.output_asset_ids = asset_ids
                job.status, job.progress, job.status_message = "completed", 1.0, "Completed"
                job.completed_at = job.heartbeat_at = utcnow()
                add_event(session, project_id, "generation.completed", "job", job.id, {"asset_ids": asset_ids, "mocked": result.mocked})
                if job.input_payload.get("canvas_generation_id"):
                    from .canvas_api import completed as canvas_completed
                    session.flush()
                    canvas_completed(session, job, result.metadata)
                update_agent_task(session, job)
                self._finish_plan(session, job_id, "review")
            if origin_workflow_id:
                from .workflow_catalog import record_execution
                record_execution(self.settings, origin_workflow_id, True)
        except Exception as exc:
            with self.session_factory.begin() as session:
                job = session.get(Job, job_id)
                if job is not None and job.status in {"running", "cancelling"}:
                    from .canvas_h3 import retain_intermediate
                    retain_intermediate(session, self.settings, job, exc)
                    job.status, job.status_message = "failed", "Execution failed"
                    job.error_code, job.error_detail, job.completed_at = type(exc).__name__, str(exc)[:8000], utcnow()
                    add_event(session, job.project_id, "generation.failed", "job", job.id, {"error_code": job.error_code})
                    update_agent_task(session, job)
                    self._finish_plan(session, job_id, "failed")
            if origin_workflow_id:
                from .workflow_catalog import record_execution
                record_execution(self.settings, origin_workflow_id, False, exc)

    def _execute_timeline_render(self, job_id: str) -> None:
        try:
            with self.session_factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return
                version = session.get(TimelineVersion, job.input_payload["timeline_version_id"])
                timeline = session.get(Timeline, job.input_payload["timeline_id"])
                project = session.get(Project, job.project_id)
                if version is None or timeline is None or project is None:
                    raise RuntimeError("timeline render inputs no longer exist")
                asset_ids = {
                    clip["source_asset_id"]
                    for track in version.tracks
                    for clip in track.get("clips", [])
                    if clip.get("source_asset_id")
                }
                assets = {asset.id: asset for asset in session.scalars(select(Asset).where(Asset.id.in_(asset_ids)))}
                output = self.settings.data_dir / "jobs" / job.id / "timeline-render.mp4"
                project_id = project.id
            rendered = self.timeline_renderer.render(version, assets, project, output, self.settings)
            with self.session_factory.begin() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return
                if job.cancellation_requested:
                    rendered.unlink(missing_ok=True)
                    job.status, job.progress = "cancelled", 0.0
                    job.status_message, job.completed_at = "Cancelled; render was not ingested", utcnow()
                    add_event(session, project_id, "timeline.render_cancelled", "job", job.id)
                    return
                media = ingest_generated(rendered, self.settings, project_id)
                asset_id = new_id()
                session.add(Asset(
                    id=asset_id, project_id=project_id, kind=media.kind, role="render",
                    path=str(media.path), content_hash=media.content_hash, mime_type=media.mime_type,
                    width=media.width, height=media.height, duration=media.duration, fps=media.fps,
                    sample_rate=media.sample_rate, parent_asset_ids=sorted(asset_ids), provider="ffmpeg",
                    workflow_run_id=job.id, approval_state="pending",
                    metadata_json={**media.metadata, "timeline_id": timeline.id, "timeline_version_id": version.id},
                ))
                job.output_asset_ids = [asset_id]
                job.status, job.progress, job.status_message = "completed", 1.0, "Timeline render completed"
                job.completed_at = job.heartbeat_at = utcnow()
                add_event(session, project_id, "asset.created", "asset", asset_id, {"job_id": job.id, "role": "render"})
                add_event(session, project_id, "timeline.render_completed", "job", job.id, {"asset_id": asset_id, "timeline_version_id": version.id})
        except Exception as exc:
            with self.session_factory.begin() as session:
                job = session.get(Job, job_id)
                if job is not None:
                    job.status, job.status_message = "failed", "Timeline render failed"
                    job.error_code, job.error_detail, job.completed_at = type(exc).__name__, str(exc)[:8000], utcnow()
                    add_event(session, job.project_id, "timeline.render_failed", "job", job.id, {"error_code": job.error_code})

    @staticmethod
    def _finish_plan(session: Session, job_id: str, state: str) -> None:
        plan = session.scalar(select(ActionPlan).where(ActionPlan.job_id == job_id))
        if plan:
            session.add(ActionPlanTransition(id=new_id(), action_plan_id=plan.id, from_state=plan.state, to_state=state))
            plan.state, plan.updated_at = state, utcnow()
