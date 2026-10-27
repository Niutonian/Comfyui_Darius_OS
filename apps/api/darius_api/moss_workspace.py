"""Project-owned boards, placements, visual notes and explicit recipe inputs."""
from copy import deepcopy
import hashlib
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field, model_validator, field_validator
from sqlalchemy import select, text, or_
from sqlalchemy.orm import load_only

from .canvas_document import CanvasContent, StrictModel, resolve_regions
from . import canvas_images as images
from .canvas_h3 import VideoConfig, PROFILES as H3_PROFILES, validate_inputs as validate_video_inputs, video_dimensions
from .canvas_moss import VERSION
from .database import (CanvasWorkspaceRecord as Workspace, MossBoardRecord as Board,
    CanvasDocumentRecord as Document, CanvasRevisionRecord as Revision, CanvasGenerationRecord as Generation,
    Project, Job, Asset, utcnow)
from .services import new_id, add_event, update_agent_task


def chat_command(value):
    # Deliberately bounded repeatable command, not an English-only substitute
    # for the normal conversation planner. No draft mutation or invented prompt.
    return bool(re.fullmatch(r"\s*(?:please\s+)?(?:generate|render|run)(?:\s+(?:this|the|selected|current))?(?:\s+(?:board|composition|image|video|edit))?(?:\s+(?:now|please))?[.!\s]*", value, re.I))


class Placement(StrictModel):
    boardId: str = Field(max_length=36)
    x: float = Field(ge=-100000, le=100000)
    y: float = Field(ge=-100000, le=100000)
    displayWidth: float = Field(default=360, ge=280, le=800)
    displayHeight: float = Field(default=450, ge=350, le=900)
    order: int = Field(default=0, ge=0, le=10000)


class SaveLayout(StrictModel):
    revision: int = Field(ge=1)
    placements: list[Placement] = Field(max_length=256)


class Reference(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    sourceBoardId: str = Field(max_length=36)
    sourceGenerationId: str = Field(max_length=36)
    assetId: str = Field(max_length=36)
    assetVersionId: str = Field(max_length=64)
    role: Literal["visual-note"] = "visual-note"


class BoardSettings(StrictModel):
    video: VideoConfig | None = None
    image: images.Config | None = None
    adapterVersion: Literal["moss-bboxes-v1", "fibo-fast-experimental-v1", "fibo-fast-turbo-v2", "fibo-dev-v1", "minimax-h3-animate-image-v1", "minimax-h3-camera-direction-v1", "minimax-h3-reference-video-v1", "flux3-klein-t2i-v1", "krea2-turbo-t2i-v1", "qwen21-t2i-v1", "qwen21-edit-v1"] = VERSION
    seed: int | str | None = None
    providerSettings: dict[Literal["moss-bboxes-v1", "fibo-fast-experimental-v1", "fibo-fast-turbo-v2", "fibo-dev-v1", "minimax-h3-animate-image-v1", "minimax-h3-camera-direction-v1", "minimax-h3-reference-video-v1", "flux3-klein-t2i-v1", "krea2-turbo-t2i-v1", "qwen21-t2i-v1", "qwen21-edit-v1"], dict] = Field(default_factory=dict)
    references: list[Reference] = Field(default_factory=list, max_length=24)

    @field_validator("seed", mode="before")
    @classmethod
    def strict_seed(cls, value):
        from .canvas_fibo import seed_value
        if value is not None:
            seed_value(value)
        return value

    @model_validator(mode="after")
    def validate_seed(self):
        from .canvas_fibo import seed_value
        if self.adapterVersion in H3_PROFILES:
            self.video = self.video or VideoConfig(activeMode=H3_PROFILES[self.adapterVersion])
            if self.video.activeMode != H3_PROFILES[self.adapterVersion]:
                raise ValueError("Video profile must match its active mode")
        elif self.video is not None:
            raise ValueError("Create a separate Video board to retain this image draft")
        if self.adapterVersion in images.PROFILES:
            self.image = self.image or images.Config(activeProfile=self.adapterVersion)
            if self.image.activeProfile != self.adapterVersion:
                raise ValueError("Image recipe must match its active draft")
        elif self.image is not None:
            raise ValueError("Create a separate Image board to preserve this draft")
        if self.seed is not None:
            value = seed_value(self.seed, maximum=2**32-1 if self.adapterVersion == VERSION else 2**64-1)
            self.seed = value if self.adapterVersion == VERSION else str(value)
        for profile, options in self.providerSettings.items():
            if set(options) - {"seed"}:
                raise ValueError("Only seed is currently configurable per profile")
            value = options.get("seed")
            if value is not None:
                value = seed_value(value, maximum=2**32-1 if profile == VERSION else 2**64-1)
            self.providerSettings[profile] = {"seed": value if profile == VERSION or value is None else str(value)}
        return self


class SaveBoard(StrictModel):
    revision: int = Field(ge=1)
    settings: BoardSettings
    archived: bool = False


class AddBoard(StrictModel):
    name: str = Field(default="Untitled board", min_length=1, max_length=200)
    x: float = Field(default=0, ge=-100000, le=100000)
    y: float = Field(default=0, ge=-100000, le=100000)
    duplicateBoardId: str | None = Field(default=None, max_length=36)
    content: CanvasContent | None = None
    settings: BoardSettings = Field(default_factory=BoardSettings)


def owned_board(session, project_id, board_id):
    board = session.get(Board, board_id)
    if not board or board.project_id != project_id:
        raise HTTPException(404, "Board does not exist in this project")
    document = session.get(Document, board.document_id)
    if not document or document.project_id != project_id:
        raise HTTPException(409, "Board document ownership is inconsistent")
    return board


def validate_references(session, project_id, target_id, references):
    seen = set()
    for ref in references:
        if ref.id in seen:
            raise HTTPException(422, "Reference IDs must be unique")
        seen.add(ref.id)
        source = owned_board(session, project_id, ref.sourceBoardId)
        generation = session.get(Generation, ref.sourceGenerationId)
        asset = session.get(Asset, ref.assetId)
        job = session.get(Job, generation.job_id) if generation else None
        if source.id == target_id:
            raise HTTPException(422, "Choose a different source board")
        if (not generation or generation.document_id != source.document_id or generation.project_id != project_id
            or not job or job.project_id != project_id or job.status != "completed"
            or not asset or asset.project_id != project_id or asset.kind != "image"
            or asset.id not in job.output_asset_ids or ref.assetVersionId != asset.content_hash):
            raise HTTPException(422, "Choose an explicit completed image version from this project's source board")


def board_snapshot(session, project_id, document_id, board_id=None, revision=None, *, validate_refs=True):
    board = session.scalar(select(Board).where(Board.document_id == document_id))
    if not board:
        if board_id:
            raise HTTPException(404, "Board does not own this Canvas document")
        return None
    owned_board(session, project_id, board.id)
    if board_id and board_id != board.id:
        raise HTTPException(404, "Board does not own this Canvas document")
    if revision is not None and revision != board.revision:
        raise HTTPException(409, "Board settings changed; refresh before generating")
    if board.archived:
        raise HTTPException(409, "Restore the archived board before submitting new work")
    settings = BoardSettings.model_validate(board.settings_json)
    if validate_refs:
        validate_references(session, project_id, board.id, settings.references)
    return {"boardId": board.id, "boardRevision": board.revision, **settings.model_dump()}


def initialize(session, project_id):
    if not session.get(Project, project_id):
        raise HTTPException(404, "Project does not exist")
    workspace = session.get(Workspace, project_id)
    if not workspace:
        workspace = Workspace(project_id=project_id, revision=1, placements_json=[])
        session.add(workspace); session.flush()
    known = set(session.scalars(select(Board.document_id).where(Board.project_id == project_id)))
    placements = deepcopy(workspace.placements_json)
    for doc in session.scalars(select(Document).where(Document.project_id == project_id).order_by(Document.created_at, Document.id)):
        if doc.id in known:
            continue
        board = Board(id=new_id(), project_id=project_id, document_id=doc.id, settings_json=BoardSettings().model_dump())
        session.add(board)
        i = len(placements)
        placements.append(Placement(boardId=board.id, x=(i % 3) * 440, y=(i // 3) * 530, order=i).model_dump())
    if placements != workspace.placements_json:
        workspace.placements_json = placements; workspace.revision += 1
    session.flush()
    return workspace


def board_view(session, board):
    doc = session.get(Document, board.document_id)
    content = CanvasContent.model_validate(session.get(Revision, (doc.id, doc.revision)).content_json)
    latest_id = session.scalar(select(Generation.id).where(Generation.document_id == doc.id).order_by(Generation.created_at.desc(), Generation.id.desc()).limit(1))
    # Overview polls only current/active/pending receipts, never every historical
    # compiled layout or full provenance record for every distant board.
    generations = session.scalars(select(Generation).join(Job, Job.id == Generation.job_id).where(Generation.document_id == doc.id,
        or_(Job.status.in_(["queued", "running", "cancelling"]), Generation.id.in_([latest_id, doc.active_generation_id])))
        .options(load_only(Generation.id, Generation.document_id, Generation.job_id, Generation.revision, Generation.seed, Generation.provenance_json))
        .order_by(Generation.created_at.desc(), Generation.id.desc())).all()
    active = session.get(Generation, doc.active_generation_id) if doc.active_generation_id else None
    def receipt(row):
        job = session.get(Job, row.job_id)
        profile = row.provenance_json.get("adapterVersion", VERSION)
        return {"id": row.id, "jobId": row.job_id, "revision": row.revision, "seed": str(row.seed) if profile.startswith(("fibo-", "minimax-h3-")) or profile in images.PROFILES else row.seed,
            "profileId": profile, "profileName": row.provenance_json.get("profileName", "MOSS"),
            "promotedFromGenerationId": row.provenance_json.get("promotedFromGenerationId"),
            "status": job.status, "statusMessage": job.status_message, "error": job.error_detail,
            "assetIds": [k for k in job.output_asset_ids if (a := session.get(Asset, k)) and a.project_id == board.project_id] if job.status == "completed" else []}
    pending = [receipt(g) for g in generations if session.get(Job, g.job_id).status in {"queued", "running", "cancelling"}]
    result = receipt(active) if active and active.document_id == doc.id else None
    asset = session.get(Asset, result["assetIds"][0]) if result and result["assetIds"] else None
    preview = session.scalar(select(Asset).where(Asset.project_id == board.project_id, Asset.role == "derivative",
        Asset.metadata_json["source_asset_id"].as_string() == asset.id,
        Asset.metadata_json["derivative_type"].as_string() == "thumbnail").limit(1)) if asset else None
    image_config = images.Config.model_validate(board.settings_json["image"]) if board.settings_json.get("image") else None
    video_config = VideoConfig.model_validate(board.settings_json["video"]) if board.settings_json.get("video") else None
    video_size = None
    if video_config:
        draft = video_config.modeDrafts[video_config.activeMode]
        video_size = video_dimensions(video_config.activeMode, draft.preset, draft.resolution)
    image_size = None
    if image_config:
        draft = image_config.drafts[image_config.activeProfile]
        first = session.get(Asset, draft.inputs[0].assetId) if draft.inputs else None
        image_size = images.output_size(image_config.activeProfile, draft, {"width": first.width, "height": first.height} if first else None)
    return {"id": board.id, "projectId": board.project_id, "documentId": doc.id, "name": doc.name,
        "kind": "image-recipe" if board.settings_json.get("adapterVersion") in images.PROFILES else "minimax-h3-video" if board.settings_json.get("adapterVersion") in H3_PROFILES else "fibo-t2i" if board.settings_json.get("adapterVersion", "").startswith("fibo-") else "moss-t2i", "revision": board.revision, "documentRevision": doc.revision,
        "settings": {**board.settings_json, "video":video_config.model_dump()} if video_config else board.settings_json, "archived": board.archived, "artboard": ({"width": image_size[0], "height": image_size[1], "preset": image_config.drafts[image_config.activeProfile].preset} if image_size else {"width": video_size["width"], "height": video_size["height"], "preset": video_size["preset"]} if video_size else content.artboard.model_dump()),
        "video": video_config.model_dump() if video_config else None,
        "prompt": (image_config.drafts[image_config.activeProfile].prompt[:280] if image_config else board.settings_json["video"]["modeDrafts"][board.settings_json["video"]["activeMode"]]["prompt"][:280] if board.settings_json.get("video") else content.globalPrompt[:280]), "regionCount": len(content.regions),
        "layout": [{"id": r["region"].id, "kind": r["region"].kind, "rect": r["rect"]} for r in resolve_regions(content) if not r["hidden"]],
        "activeResult": result, "previewAssetId": preview.id if preview else None,
        "latest": receipt(generations[0]) if generations else None, "jobs": pending,
        "newResult": bool(generations and session.get(Job, generations[0].job_id).status == "completed" and generations[0].id != doc.active_generation_id)}


def workspace_view(session, workspace):
    boards = session.scalars(select(Board).where(Board.project_id == workspace.project_id).order_by(Board.id)).all()
    return {"projectId": workspace.project_id, "schemaVersion": workspace.schema_version, "revision": workspace.revision,
        "placements": workspace.placements_json, "boards": [board_view(session, b) for b in boards],
        "capacity": 1, "queuePolicy": "Shared local GPU lease; FIFO ready jobs. External ComfyUI occupancy checked."}


def router(settings, session_factory, generate):
    routes = APIRouter(prefix="/projects/{project_id}", tags=["moss-workspace"])

    @routes.get("/canvas-workspace")
    def get_workspace(project_id: str):
        # Status polling is read-only once documents have their board mapping.
        # A writer may be ingesting output files; WAL readers can still see the
        # last committed Running/Queued receipt without waiting for its lock.
        with session_factory() as session:
            session.execute(text("BEGIN"))
            if not session.get(Project, project_id):
                raise HTTPException(404, "Project does not exist")
            workspace = session.get(Workspace, project_id)
            unmapped = session.scalar(select(Document.id).outerjoin(Board, Board.document_id == Document.id)
                .where(Document.project_id == project_id, Board.id.is_(None)).limit(1))
            if workspace is not None and unmapped is None:
                return workspace_view(session, workspace)
        # Lazy migration is the exceptional write path; recheck under the lock.
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            return workspace_view(session, initialize(session, project_id))

    @routes.post("/canvas-workspace/layout")
    def save_layout(project_id: str, payload: SaveLayout):
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            workspace = initialize(session, project_id)
            if workspace.revision != payload.revision:
                raise HTTPException(409, "Workspace layout changed on another device. Your placement draft is retained.")
            ids = [p.boardId for p in payload.placements]
            if len(ids) != len(set(ids)) or set(ids) != set(session.scalars(select(Board.id).where(Board.project_id == project_id))):
                raise HTTPException(422, "Keep exactly one placement per board; use Archive instead of deleting documents")
            workspace.placements_json = [p.model_dump() for p in payload.placements]; workspace.revision += 1
            add_event(session, project_id, "canvas.workspace_saved", "workspace", project_id)
            return workspace_view(session, workspace)

    @routes.post("/canvas-workspace/boards", status_code=201)
    def add_board(project_id: str, payload: AddBoard):
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            workspace = initialize(session, project_id)
            if len(workspace.placements_json) >= 256:
                raise HTTPException(422, "A workspace supports up to 256 boards")
            config = payload.settings.model_dump()
            content = payload.content or CanvasContent(name=payload.name)
            if payload.duplicateBoardId:
                source = owned_board(session, project_id, payload.duplicateBoardId)
                document = session.get(Document, source.document_id)
                content = CanvasContent.model_validate(deepcopy(session.get(Revision, (document.id, document.revision)).content_json))
                content.name = payload.name
                config = deepcopy(source.settings_json)
            if config.get("video"):
                try: validate_video_inputs(session, project_id, VideoConfig.model_validate(config["video"]))
                except ValueError as exc: raise HTTPException(422, str(exc)) from exc
            if config.get("image"):
                try: images.validate_inputs(session, project_id, images.Config.model_validate(config["image"]))
                except ValueError as exc: raise HTTPException(422, str(exc)) from exc
            document = Document(id=new_id(), project_id=project_id, name=content.name, revision=1)
            session.add(document); session.flush()
            session.add(Revision(document_id=document.id, revision=1, content_json=content.model_dump()))
            board = Board(id=new_id(), project_id=project_id, document_id=document.id, settings_json=config)
            session.add(board); session.flush()
            # Look for a nearby free slot; no semantic document changes involved.
            x, y = payload.x, payload.y
            for _ in range(256):
                if all(abs(x-p["x"]) >= 400 or abs(y-p["y"]) >= 500 for p in workspace.placements_json): break
                x += 420
                if x > payload.x + 3*420: x, y = payload.x, y+520
            workspace.placements_json = [*workspace.placements_json, Placement(boardId=board.id, x=x, y=y, order=len(workspace.placements_json)).model_dump()]
            workspace.revision += 1
            add_event(session, project_id, "canvas.board_added", "board", board.id)
            return {"boardId": board.id, "workspace": workspace_view(session, workspace)}

    @routes.post("/canvas-workspace/boards/{board_id}")
    def save_board(project_id: str, board_id: str, payload: SaveBoard):
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            board = owned_board(session, project_id, board_id)
            if board.revision != payload.revision:
                raise HTTPException(409, "Board settings changed on another device; refresh before updating")
            def family(profile):
                return "video" if profile in H3_PROFILES else "recipe" if profile in images.PROFILES else "layout"
            if family(board.settings_json.get("adapterVersion")) != family(payload.settings.adapterVersion):
                raise HTTPException(422, "Create a separate board when changing board families")
            if payload.settings.image:
                try: images.validate_inputs(session, project_id, payload.settings.image)
                except ValueError as exc: raise HTTPException(422, str(exc)) from exc
            if payload.settings.video:
                try: validate_video_inputs(session, project_id, payload.settings.video)
                except ValueError as exc: raise HTTPException(422, str(exc)) from exc
            validate_references(session, project_id, board.id, payload.settings.references)
            board.settings_json = payload.settings.model_dump(); board.archived = payload.archived; board.revision += 1
            add_event(session, project_id, "canvas.board_saved", "board", board.id)
            return board_view(session, board)

    @routes.post("/canvas-workspace/boards/{board_id}/cancel/{job_id}")
    def cancel(project_id: str, board_id: str, job_id: str):
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            board = owned_board(session, project_id, board_id)
            generation = session.scalar(select(Generation).where(Generation.document_id == board.document_id, Generation.job_id == job_id))
            if not generation:
                raise HTTPException(404, "Job does not belong to this board")
            job = session.get(Job, job_id)
            if job.status != "queued":
                raise HTTPException(409, "Only queued work can be safely cancelled here. Running work is not globally interrupted.")
            job.status = "cancelled"; job.cancellation_requested = True
            job.status_message = "Cancelled before execution"; job.completed_at = utcnow()
            add_event(session, project_id, "job.cancellation_requested", "job", job.id, {"status": "cancelled"})
            update_agent_task(session, job)
        return {"jobId": job_id, "status": "cancelled"}

    return routes
