"""Project-scoped Canvas storage and explicit, idempotent composition jobs."""
from copy import deepcopy
from datetime import timezone
import hashlib
from pathlib import Path
from secrets import randbelow
import threading

from fastapi import APIRouter, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select, text

from .atomic_files import atomic_json
from .canvas_document import CanvasContent, StrictModel, dimensions, PRESETS, resolve_regions
from .canvas_moss import VERSION, compile_graph, example, readiness, digest
from . import canvas_fibo as fibo
from . import canvas_h3 as h3
from . import canvas_images as images
from .database import (CanvasDocumentRecord as Document, CanvasRevisionRecord as Revision,
                       CanvasGenerationRecord as Generation, Project, Job, Asset, utcnow)
from .services import new_id, add_event, enqueue_request, register_workflows
from .workflows import WorkflowContract, WorkflowOutput, RuntimeMapping, WorkflowInput, WorkflowMapping

_locks = [threading.RLock() for _ in range(64)]


class SaveCanvas(StrictModel):
    revision: int = Field(ge=1)
    content: CanvasContent


class GenerateCanvas(StrictModel):
    revision: int = Field(ge=1)
    idempotencyKey: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    seed: int | str | None = None
    approved: bool = Field(default=False, strict=True)
    boardId: str | None = Field(default=None, max_length=36)
    boardRevision: int | None = Field(default=None, ge=1)
    profileId: str | None = None
    promotedFromGenerationId: str | None = Field(default=None, max_length=36)

    @field_validator("seed", mode="before")
    @classmethod
    def concrete_seed(cls, value):
        if value is not None:
            fibo.seed_value(value)
        return value


class SelectGeneration(StrictModel):
    generationId: str


def owned(session, project_id, document_id=None):
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "Project does not exist")
    if document_id is not None:
        doc = session.get(Document, document_id)
        if doc is None or doc.project_id != project_id:
            raise HTTPException(404, "Canvas does not exist in this project")
        return doc


def generation_view(session, row):
    job = session.get(Job, row.job_id)
    # Ownership is rechecked on every result read, not inferred from filenames.
    if not job or job.project_id != row.project_id:
        raise HTTPException(409, "Canvas result provenance is inconsistent")
    assets = [key for key in job.output_asset_ids if (asset := session.get(Asset, key)) and asset.project_id == row.project_id]
    return {"id": row.id, "revision": row.revision, "jobId": job.id, "seed": str(row.seed) if row.provenance_json.get("profileId") in {*fibo.PROFILES, *h3.PROFILES, *images.PROFILES} else row.seed,
            "status": job.status, "statusMessage": job.status_message, "error": job.error_detail,
            "assetIds": assets if job.status == "completed" or row.provenance_json.get("partial") else [],
            "provenance": {key: value for key, value in row.provenance_json.items() if key != "compiledLayout"},
            "createdAt": row.created_at.replace(tzinfo=timezone.utc).isoformat()}


def document_view(session, doc):
    revision = session.get(Revision, (doc.id, doc.revision))
    generations = session.scalars(select(Generation).where(Generation.document_id == doc.id)
        .order_by(Generation.created_at.desc()).limit(100)).all()
    return {"id": doc.id, "projectId": doc.project_id, "revision": doc.revision, "content": revision.content_json,
            "activeGenerationId": doc.active_generation_id, "updatedAt": doc.updated_at.isoformat(),
            "generations": [generation_view(session, row) for row in generations]}


def protect_locked(before, after):
    updated = {r.id: r for r in after.regions}
    for resolved in resolve_regions(before):
        region = resolved["region"]
        other = updated.get(region.id)
        if resolved["locked"] and (other is None or region.model_dump(exclude={"locked"}) != other.model_dump(exclude={"locked"})):
            raise HTTPException(409, f"Unlock {region.name} or its parent before editing it")


def completed(session, job, provider_metadata):
    """Called in the existing worker's successful ingestion transaction."""
    key = job.input_payload.get("canvas_generation_id")
    if not key:
        return
    generation = session.get(Generation, key)
    if not generation or generation.job_id != job.id or generation.project_id != job.project_id:
        raise ValueError("Canvas job/revision provenance mismatch")
    generation.provenance_json = {**generation.provenance_json,
        "compiledLayout": provider_metadata.get("canvas_compiled_layout"), "comfyPromptId": job.external_job_id,
        "environment": provider_metadata.get("canvas_environment") or {"unavailable": True},
        "executedGraphDigest": provider_metadata.get("canvas_executed_graph_digest")}
    if generation.provenance_json.get("profileId") in fibo.PROFILES:
        actual = provider_metadata.get("canvas_conditioning_prompt")
        if actual != generation.provenance_json.get("conditioningPrompt"):
            raise ValueError("FIBO conditioning receipt does not match the immutable saved prompt")
        generation.provenance_json = {**generation.provenance_json, "conditioningPromptVerified": True,
            "conditioningPrompt": actual, "conditioningPromptHash": fibo.text_hash(actual)}
    if generation.provenance_json.get("profileId") in h3.PROFILES:
        h3.verify_outputs(session, job, generation.provenance_json)
    if generation.provenance_json.get("profileId") in images.PROFILES:
        images.completed(session, job, generation, provider_metadata)
    doc = session.get(Document, generation.document_id)
    # Video output and the editable input draft are separate. A longer video
    # render may finish after a draft edit without losing its displayed result.
    # Explicit version choices and newer generation requests still take priority.
    latest = session.scalar(select(Generation.id).where(Generation.document_id == generation.document_id)
        .order_by(Generation.created_at.desc(), Generation.id.desc()).limit(1))
    board_revision_matches = True
    board_exists = True
    if generation.provenance_json.get("board"):
        from .database import MossBoardRecord
        snapshot = generation.provenance_json["board"]
        board = session.get(MossBoardRecord, snapshot["boardId"])
        board_exists = bool(board)
        board_revision_matches = bool(board and board.revision == snapshot["boardRevision"])
    draft_matches = board_revision_matches and doc and doc.revision == generation.revision
    video_result = generation.provenance_json.get("profileId") in h3.PROFILES and board_exists
    if doc and (draft_matches or video_result) and latest == generation.id and doc.selection_version == generation.selection_version:
        doc.active_generation_id = generation.id
        doc.selection_version += 1
    for asset_id in job.output_asset_ids:
        asset = session.get(Asset, asset_id)
        if asset and asset.project_id == job.project_id:
            asset.metadata_json = {**asset.metadata_json, "canvas": {
                "documentId": generation.document_id, "revision": generation.revision,
                "generationId": generation.id, "adapterVersion": generation.provenance_json.get("adapterVersion", VERSION),
                "boardId": generation.provenance_json.get("board", {}).get("boardId")}}
    add_event(session, job.project_id, "canvas.generated", "canvas", generation.document_id,
              {"revision": generation.revision, "generation_id": generation.id})


def router(settings, session_factory, registry):
    routes = APIRouter(prefix="/api/v1", tags=["canvas"])

    from . import board_setup
    from . import comfy_connection

    class ComfyConnectionRequest(StrictModel):
        root: str = Field(default='', max_length=1024)
        baseUrl: str = Field(default='http://127.0.0.1:8188', max_length=120)
        outputDir: str = Field(default='', max_length=1024)

    @routes.get('/canvas/connection')
    def get_comfy_connection():
        return comfy_connection.describe(settings)

    @routes.post('/canvas/connection/detect')
    def detect_comfy_connection(payload: ComfyConnectionRequest):
        try:
            return comfy_connection.detect(settings, payload.baseUrl)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @routes.post('/canvas/connection')
    def save_comfy_connection(payload: ComfyConnectionRequest):
        with board_setup._guard:
            if any(key[0] == str(settings.data_dir.resolve()) for key in board_setup._active):
                raise HTTPException(409, 'Wait for the current board dependency check/preparation to finish before changing its ComfyUI connection.')
            try:
                return comfy_connection.save(settings, payload.root, payload.baseUrl, output_dir=payload.outputDir or None)
            except (ValueError, OSError) as exc:
                raise HTTPException(422, str(exc)) from exc

    class PrepareBoard(StrictModel):
        planDigest: str = Field(pattern=r'^[a-f0-9]{64}$')
        restart: bool = True

    @routes.get('/canvas/setup/{profile}')
    def board_setup_status(profile: str):
        try:
            return board_setup.status(settings, profile)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @routes.post('/canvas/setup/{profile}/check')
    def check_board_setup(profile: str):
        try:
            return board_setup.begin(settings, profile)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @routes.post('/canvas/setup/{profile}/prepare')
    def prepare_board_setup(profile: str, payload: PrepareBoard):
        try:
            return board_setup.begin(settings, profile, confirmed=payload.planDigest, restart=payload.restart)
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @routes.get("/canvas/engine")
    def engine(check: bool = False, profile: str = VERSION):
        result = {"adapterVersion": VERSION, "capabilities": {"composition": True, "references": False,
            "pixelProtection": False, "independentLayers": False}, "presets": [
                {"id": key, "name": value[0], "width": dimensions(key)[0], "height": dimensions(key)[1]} for key, value in PRESETS.items()]}
        result["profiles"] = [{"id": VERSION, "family": "moss", "name": "MOSS", "steps": 25, "cfg": 2.5},
            *[{k: v for k, v in value.items() if k not in {"templateDigest", "manifestDigest"}} for value in fibo.PROFILES.values() if not value.get("deprecated")]]
        if profile != VERSION and profile not in fibo.PROFILES:
            raise HTTPException(422, "Unknown Canvas workflow profile")
        result["selectedProfile"] = profile
        if profile in fibo.PROFILES:
            result["adapterVersion"] = profile
        if check:
            try:
                result["readiness"] = fibo.readiness(settings, profile=profile) if profile in fibo.PROFILES else readiness(settings)
            except Exception as exc:
                result["readiness"] = {"ready": False, "issues": [str(exc)]}
        return result

    @routes.get("/canvas/image/engine")
    def image_engine(check: bool = False):
        return {"profiles": [{"id": profile, "name": name, "defaults": images.defaults(profile).model_dump(),
            "inputs": 10 if profile == images.EDIT else 0,
            "readiness": images.readiness(settings, profile) if check else None,
            "source": images.artifacts(settings, profile)[1]["sourceUiDigest"]} for profile, name in images.PROFILES.items()],
            "presets": [{"id": key, "name": value[0]} for key, value in PRESETS.items()]}

    @routes.get("/canvas/video/engine")
    def video_engine(check: bool = False):
        return {"family": "minimax-h3", "modes": [{"id": mode, "profileId": profile,
            **h3.video_dimensions(mode), "timings": [h3.timing(mode, s) for s in h3.DURATIONS],
            "sizes": [h3.video_dimensions(mode, preset, resolution) for preset in PRESETS for resolution in h3.RESOLUTIONS],
            "readiness": h3.readiness(settings, profile) if check else None,
            "referenceImages": 9 if mode == "reference-video" else 1,
            "referenceVideo": False, "referenceAudio": False,
            "note": "Motion/audio-reference branches require additional runtime validation; generated audio is retained."}
            for profile, mode in h3.PROFILES.items()],
            "presets": [{"id": key, "name": value[0]} for key, value in PRESETS.items()],
            "resolutions": [{"id": key, "name": value} for key, value in h3.RESOLUTIONS.items()],
            "durations": list(h3.DURATIONS), "fps": 24}

    @routes.get("/canvas/example")
    def load_example(profile: str = VERSION):
        if profile == VERSION:
            return example(settings)
        if profile not in fibo.PROFILES:
            raise HTTPException(422, "Unknown Canvas workflow profile")
        return fibo.example(settings, profile)

    @routes.get("/projects/{project_id}/canvases")
    def list_documents(project_id: str):
        with session_factory() as session:
            owned(session, project_id)
            return [{"id": d.id, "name": d.name, "revision": d.revision, "updatedAt": d.updated_at.isoformat()}
                for d in session.scalars(select(Document).where(Document.project_id == project_id).order_by(Document.updated_at.desc()))]

    @routes.post("/projects/{project_id}/canvases", status_code=201)
    def create_document(project_id: str, content: CanvasContent):
        with session_factory.begin() as session:
            owned(session, project_id)
            doc = Document(id=new_id(), project_id=project_id, name=content.name, revision=1)
            session.add(doc); session.flush()
            session.add(Revision(document_id=doc.id, revision=1, content_json=content.model_dump()))
            add_event(session, project_id, "canvas.created", "canvas", doc.id)
            session.flush()
            return document_view(session, doc)

    @routes.get("/projects/{project_id}/canvases/{document_id}")
    def get_document(project_id: str, document_id: str):
        with session_factory() as session:
            return document_view(session, owned(session, project_id, document_id))

    @routes.post("/projects/{project_id}/canvases/{document_id}/save")
    def save_document(project_id: str, document_id: str, payload: SaveCanvas):
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            doc = owned(session, project_id, document_id)
            if doc.revision != payload.revision:
                raise HTTPException(409, "This canvas changed on another device. Your draft is retained; reload the saved version or export your draft before resolving it.")
            previous = session.get(Revision, (document_id, doc.revision))
            if previous.content_json == payload.content.model_dump():
                return document_view(session, doc)
            protect_locked(CanvasContent.model_validate(previous.content_json), payload.content)
            doc.revision += 1; doc.name = payload.content.name; doc.updated_at = utcnow()
            session.add(Revision(document_id=doc.id, revision=doc.revision, content_json=payload.content.model_dump()))
            add_event(session, project_id, "canvas.saved", "canvas", doc.id, {"revision": doc.revision})
            session.flush()
            return document_view(session, doc)

    @routes.get("/projects/{project_id}/canvases/{document_id}/revisions/{revision}")
    def get_revision(project_id: str, document_id: str, revision: int):
        with session_factory() as session:
            owned(session, project_id, document_id)
            row = session.get(Revision, (document_id, revision))
            if not row:
                raise HTTPException(404, "Canvas revision does not exist")
            return {"revision": row.revision, "content": row.content_json}

    @routes.post("/projects/{project_id}/canvases/{document_id}/select-result")
    def select_result(project_id: str, document_id: str, payload: SelectGeneration):
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            doc = owned(session, project_id, document_id)
            generation = session.get(Generation, payload.generationId)
            if not generation or generation.document_id != doc.id or generation.project_id != project_id:
                raise HTTPException(404, "Result does not belong to this canvas")
            if session.get(Job, generation.job_id).status != "completed":
                raise HTTPException(409, "This result has not completed")
            doc.active_generation_id = generation.id; doc.selection_version += 1
            add_event(session, project_id, "canvas.result_selected", "canvas", doc.id)
            return document_view(session, doc)

    @routes.get("/projects/{project_id}/canvases/{document_id}/generations/{generation_id}/provenance")
    def provenance(project_id: str, document_id: str, generation_id: str):
        with session_factory() as session:
            owned(session, project_id, document_id)
            generation = session.get(Generation, generation_id)
            if not generation or generation.document_id != document_id or generation.project_id != project_id:
                raise HTTPException(404, "Generation does not exist in this canvas")
            return generation.provenance_json

    @routes.post("/projects/{project_id}/canvases/{document_id}/generate")
    def generate(project_id: str, document_id: str, payload: GenerateCanvas):
        current_settings = comfy_connection.effective_settings(settings)
        return generate_with_settings(project_id, document_id, payload, current_settings)

    def generate_with_settings(project_id: str, document_id: str, payload: GenerateCanvas, settings):
        if not payload.approved:
            raise HTTPException(422, "Generate composition requires explicit approval for one whole-image local run")
        lock = _locks[int(hashlib.sha256(document_id.encode()).hexdigest(), 16) % len(_locks)]
        with lock:
            with session_factory() as session:
                doc = owned(session, project_id, document_id)
                existing = session.scalar(select(Generation).where(Generation.document_id == doc.id, Generation.idempotency_key == payload.idempotencyKey))
                if existing:
                    if (existing.revision != payload.revision or (payload.seed is not None and fibo.seed_value(payload.seed) != existing.seed)
                            or existing.provenance_json.get("promotedFromGenerationId") != payload.promotedFromGenerationId
                            or (payload.profileId is not None and existing.provenance_json.get("adapterVersion", VERSION) != payload.profileId)):
                        raise HTTPException(409, "This request key belongs to a different Canvas generation")
                    return generation_view(session, existing)
                if settings.comfyui_output_dir is not None and not settings.comfyui_output_dir.is_dir():
                    raise HTTPException(422, 'Board setup required: Connect ComfyUI so Darius can collect the generated files from its output folder.')
                if doc.revision != payload.revision and not payload.promotedFromGenerationId:
                    raise HTTPException(409, "Save the current canvas before generating its composition")
                revision_record = session.get(Revision, (doc.id, payload.revision))
                if not revision_record:
                    raise HTTPException(422, "The saved composition snapshot is unavailable")
                snapshot = CanvasContent.model_validate(revision_record.content_json)
                selection_version = doc.selection_version
                from .moss_workspace import board_snapshot, BoardSettings, validate_references
                board = board_snapshot(session, project_id, document_id, payload.boardId, payload.boardRevision,
                    validate_refs=not bool(payload.promotedFromGenerationId))
                profile = payload.profileId or (board.get("adapterVersion") if board else VERSION)
                if board_setup.host_installation_locked(settings):
                    raise HTTPException(409, 'ComfyUI dependencies are being prepared. Wait for board setup to finish, then generate your saved draft.')
                if profile in images.PROFILES:
                    return images.generate(settings, session_factory, registry, project_id, document_id, payload)
                if profile in h3.PROFILES:
                    return h3.generate(settings, session_factory, registry, project_id, document_id, payload)
                source = None
                if payload.promotedFromGenerationId:
                    original = session.get(Generation, payload.promotedFromGenerationId)
                    original_job = session.get(Job, original.job_id) if original else None
                    if (not original or original.project_id != project_id or original.document_id != document_id
                            or original.revision != payload.revision or not original_job or original_job.project_id != project_id
                            or original_job.status != "completed"
                            or not any((asset := session.get(Asset, key)) and asset.project_id == project_id and asset.kind == "image" for key in original_job.output_asset_ids)):
                        raise HTTPException(422, "Choose a completed fast preview with a retained image from this board")
                    source = deepcopy(original.provenance_json)
                    if (source.get("profileId") not in {fibo.FAST, fibo.LEGACY_FAST} or source.get("conditioningPromptVerified") is not True or source.get("documentSnapshot") != snapshot.model_dump()
                            or source.get("board", {}).get("boardId") != (board or {}).get("boardId")
                            or (payload.profileId is not None and payload.profileId != fibo.DEV)
                            or (payload.seed is not None and fibo.seed_value(payload.seed) != original.seed)):
                        raise HTTPException(422, "This preview's saved profile, board or composition snapshot cannot be promoted")
                    profile = fibo.DEV
                elif board and profile != board["adapterVersion"]:
                    raise HTTPException(409, "Board profile changed; refresh before generating")
                if profile not in {VERSION, *fibo.PROFILES}:
                    raise HTTPException(422, "Unknown Canvas profile")
            configured_seed = payload.seed if payload.seed is not None else board.get("seed") if board else None
            if source:
                configured_seed = source["seed"]
            try:
                seed = fibo.seed_value(configured_seed if configured_seed is not None else randbelow(2**32), maximum=2**32-1 if profile == VERSION else 2**64-1)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            generation_id = new_id()
            try:
                graph, provenance = fibo.compile_graph(settings, snapshot, seed, profile, source) if profile in fibo.PROFILES else compile_graph(settings, snapshot, seed)
                if board:
                    provenance["board"] = {**(source["board"] if source else board), "boardRevision": board["boardRevision"],
                        "adapterVersion": profile, "seed": str(seed) if profile in fibo.PROFILES else seed}
                if source:
                    provenance["promotedFromGenerationId"] = payload.promotedFromGenerationId
                    provenance["sourceDocumentRevision"] = payload.revision
                provenance["projectId"] = project_id
                provenance["generationId"] = generation_id
                provenance["documentId"] = document_id
                provenance["documentRevision"] = payload.revision
                try:
                    status = fibo.readiness(settings, graph, profile) if profile in fibo.PROFILES else readiness(settings, graph)
                except Exception as exc:
                    raise ValueError('Board setup required: ' + str(exc)) from exc
                if not status["ready"]:
                    raise ValueError("Board setup required: " + "; ".join(status["issues"]))
            except Exception as exc:
                raise HTTPException(422, str(exc) + ". Canvas draft and previous results are retained; no render was submitted.") from exc
            workflow_id = "canvas-" + generation_id
            graph_path = settings.workflow_definitions_dir / "graphs" / (workflow_id + ".json")
            atomic_json(graph_path, graph)
            from .providers import ComfyMcpProvider
            try:
                validation = ComfyMcpProvider(settings).validate_api_graph(graph_path, graph, timeout=60)
                if validation.get("valid") is not True or validation.get("errors"):
                    raise ValueError(str(validation.get("errors") or "ComfyUI rejected the Canvas graph"))
            except Exception as exc:
                raise HTTPException(422, str(exc) + ". No render was queued; your Canvas draft is retained.") from exc
            sampler = provenance["sampler"] if profile in fibo.PROFILES else "18:7"
            sink = provenance["outputNode"] if profile in fibo.PROFILES else "9"
            contract = WorkflowContract(id=workflow_id, name=snapshot.name + " · Canvas", version=profile,
                capability="text-to-image", execution_provider="local-comfyui", workflow_reference=str(graph_path.resolve()),
                required_inputs=[WorkflowInput(key="seed", type="integer", default=seed, minimum=0,
                    maps_to=WorkflowMapping(slot=f"{sampler}.seed"))], output=WorkflowOutput(kind="image"),
                runtime_mapping=RuntimeMapping(filename_prefix_slot=f"{sink}.filename_prefix", api_format=True),
                output_node_ids=[sink], internal_only=True, project_id=project_id, requires_approval=True)
            atomic_json(settings.workflow_definitions_dir / (workflow_id + ".json"), contract.model_dump())
            registry.load(); register_workflows(session_factory, registry)
            with session_factory.begin() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                doc = owned(session, project_id, document_id)
                existing = session.scalar(select(Generation).where(Generation.document_id == doc.id, Generation.idempotency_key == payload.idempotencyKey))
                if existing:
                    return generation_view(session, existing)
                # The immutable revision was authorized before preflight. Newer
                # drafts/board selection cannot mutate or invalidate that snapshot.
                if session.get(Revision, (document_id, payload.revision)).content_json != snapshot.model_dump():
                    raise HTTPException(409, "The saved Canvas snapshot changed; no render was queued")
                if board:
                    from .moss_workspace import owned_board
                    owned_board(session, project_id, board["boardId"])
                    captured_board = provenance["board"]
                    validate_references(session, project_id, board["boardId"], BoardSettings.model_validate({k: captured_board[k] for k in ("adapterVersion", "seed", "references")}).references)
                job = enqueue_request(session_factory, registry, project_id, workflow_id, snapshot.globalPrompt or snapshot.name,
                                      {"seed": seed}, True, _session=session, allow_internal=True)
                job.input_payload = {**job.input_payload, "canvas_generation_id": generation_id,
                    "canvas_document_id": doc.id, "canvas_revision": payload.revision, "canvas_graph_digest": digest(graph),
                    "canvas_contract_digest": digest(contract.model_dump(mode="json")),
                    "canvas_board_id": board["boardId"] if board else None,
                    "worker_ready": True,
                    "render_name": snapshot.name + " · composition"}
                generation = Generation(id=generation_id, document_id=doc.id, project_id=project_id, revision=payload.revision,
                    job_id=job.id, idempotency_key=payload.idempotencyKey, seed=seed,
                    selection_version=selection_version, provenance_json=provenance)
                generation.provenance_json = {**provenance, "contractDigest": job.input_payload["canvas_contract_digest"]}
                session.add(generation)
                add_event(session, project_id, "canvas.queued", "canvas", doc.id, {"job_id": job.id, "revision": payload.revision})
                session.flush()
                receipt = generation_view(session, generation)
            try:
                from .local_render import launch_local_job
                launch_local_job(settings, receipt["jobId"])
            except OSError:
                receipt["launchError"] = "Job saved but worker could not start. Use Start worker in this canvas; do not resubmit."
            return receipt

    @routes.post("/projects/{project_id}/canvases/{document_id}/generations/{generation_id}/start")
    def start(project_id: str, document_id: str, generation_id: str):
        with session_factory() as session:
            owned(session, project_id, document_id)
            generation = session.get(Generation, generation_id)
            if not generation or generation.document_id != document_id or generation.project_id != project_id:
                raise HTTPException(404, "Generation does not exist in this canvas")
            job = session.get(Job, generation.job_id)
            if job.status != "queued":
                return generation_view(session, generation)
            from .local_render import launch_local_job
            launch_local_job(settings, job.id)
            return generation_view(session, generation)

    from .moss_workspace import router as workspace_router
    routes.include_router(workspace_router(settings, session_factory, generate))
    routes.generate_composition = generate
    return routes
