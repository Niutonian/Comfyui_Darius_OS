"""Explicit, revision-safe prompt edits. This module has no generation dispatcher."""
from copy import deepcopy
import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import select, text

from .canvas_document import CanvasContent, StrictModel
from .database import (CanvasDocumentRecord as Document, CanvasRevisionRecord as Revision,
                       Conversation, Message, ProjectEvent, utcnow)
from .services import add_event


class ApplyPrompt(StrictModel):
    transferId: UUID
    sourceMessageId: str = Field(min_length=1, max_length=36)
    sourceDraftId: str | None = Field(default=None, max_length=80)
    sourceText: str = Field(min_length=1, max_length=30000)
    text: str = Field(min_length=1, max_length=30000)
    boardRevision: int = Field(ge=1)
    documentRevision: int = Field(ge=1)
    destination: str = Field(min_length=1, max_length=160)


def resolve_target(board):
    from . import canvas_images as images, canvas_h3 as h3
    from .canvas_fibo import PROFILES as FIBO
    from .canvas_moss import VERSION
    profile = board.settings_json.get("adapterVersion", VERSION)
    if profile in images.PROFILES:
        config = images.Config.model_validate(board.settings_json["image"])
        return {"key": "image:"+config.activeProfile, "label": images.PROFILES[config.activeProfile]+" / Image prompt",
                "family": "Image", "mode": config.activeProfile, "maxLength": 30000}
    if profile in h3.PROFILES:
        config = h3.VideoConfig.model_validate(board.settings_json["video"])
        label = {"animate-image":"Animate image", "camera-direction":"Camera direction", "reference-video":"Reference video"}[config.activeMode]
        return {"key": "video:"+config.activeMode, "label": "H3 "+label+" / Scene and action",
                "family": "Video", "mode": config.activeMode, "maxLength": 30000}
    if profile == VERSION or profile in FIBO:
        family = "MOSS" if profile == VERSION else "FIBO"
        return {"key": "layout:"+profile, "label": family+" / Global scene prompt", "family": family,
                "mode": profile, "maxLength": 6000}
    raise HTTPException(422, "This board has no registered prompt destination")


def target_view(session, board):
    destination = resolve_target(board)
    doc = session.get(Document, board.document_id)
    revision = session.get(Revision, (doc.id, doc.revision))
    key = destination["key"]
    if key.startswith("image:"):
        value = board.settings_json["image"]["drafts"][destination["mode"]]["prompt"]
    elif key.startswith("video:"):
        value = board.settings_json["video"]["modeDrafts"][destination["mode"]]["prompt"]
    else:
        value = revision.content_json["globalPrompt"]
    return {"boardId":board.id, "documentId":doc.id, "name":doc.name, "archived":board.archived,
            "boardRevision":board.revision, "documentRevision":doc.revision, "destination":destination, "text":value}


def write_prompt(session, board, value):
    target = resolve_target(board)
    doc = session.get(Document, board.document_id)
    previous = session.get(Revision, (doc.id, doc.revision))
    if target["key"].startswith("layout:"):
        content = CanvasContent.model_validate({**previous.content_json, "globalPrompt":value})
        doc.revision += 1
        session.add(Revision(document_id=doc.id, revision=doc.revision, content_json=content.model_dump()))
    else:
        config = deepcopy(board.settings_json)
        if target["key"].startswith("image:"):
            config["image"]["drafts"][target["mode"]]["prompt"] = value
        else:
            config["video"]["modeDrafts"][target["mode"]]["prompt"] = value
        board.settings_json = config
    board.revision += 1
    doc.updated_at = utcnow()
    session.flush()


def router(session_factory):
    from .moss_workspace import owned_board, board_view
    from .canvas_api import document_view
    routes = APIRouter(prefix="/api/v1/projects/{project_id}/canvas-workspace/boards", tags=["prompt-transfer"])

    def response(session, board, transfer, undone=False):
        return {"transferId":transfer.id, "undone":undone, "target":target_view(session, board),
                "board":board_view(session, board), "document":document_view(session, session.get(Document, board.document_id))}

    @routes.get("/{board_id}/prompt")
    def review(project_id: str, board_id: str):
        with session_factory() as session:
            return target_view(session, owned_board(session, project_id, board_id))

    @routes.post("/{board_id}/prompt")
    def apply(project_id: str, board_id: str, payload: ApplyPrompt):
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            board = owned_board(session, project_id, board_id)
            fingerprint = hashlib.sha256(json.dumps(payload.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            existing = session.get(ProjectEvent, str(payload.transferId))
            if existing:
                if existing.project_id != project_id or existing.entity_id != board_id or existing.event_type != "canvas.prompt_applied" or existing.payload.get("fingerprint") != fingerprint:
                    raise HTTPException(409, "This transfer key belongs to another edit")
                return response(session, board, existing, bool(session.scalar(select(ProjectEvent.id).where(ProjectEvent.event_type == "canvas.prompt_undone", ProjectEvent.payload["transferId"].as_string() == existing.id))))
            source = session.get(Message, payload.sourceMessageId)
            conversation = session.get(Conversation, source.conversation_id) if source else None
            if not source or source.role != "assistant" or not conversation or conversation.project_id != project_id:
                raise HTTPException(422, "Choose a reply from this project's conversation")
            if payload.sourceDraftId:
                from .creative_chat import prompt_drafts
                drafts = prompt_drafts(source.content)
                if not any(d["id"] == payload.sourceDraftId and d["text"] == payload.sourceText for d in drafts):
                    raise HTTPException(422, "The selected prompt draft no longer matches this reply")
            elif payload.sourceText not in source.content:
                raise HTTPException(422, "The selected text is not part of this reply")
            before = target_view(session, board)
            if board.archived or before["boardRevision"] != payload.boardRevision or before["documentRevision"] != payload.documentRevision or before["destination"]["key"] != payload.destination:
                raise HTTPException(409, "The board changed or was archived. Refresh the target review; your prompt is retained.")
            if not payload.text.strip() or len(payload.text) > before["destination"]["maxLength"]:
                raise HTTPException(422, f"This prompt field accepts 1–{before['destination']['maxLength']} characters")
            if payload.text != before["text"]:
                write_prompt(session, board, payload.text)
            after = target_view(session, board)
            transfer = ProjectEvent(id=str(payload.transferId), project_id=project_id, event_type="canvas.prompt_applied", entity_type="board", entity_id=board.id,
                payload={"fingerprint":fingerprint, "sourceMessageId":source.id, "sourceDraftId":payload.sourceDraftId,
                         "destination":payload.destination, "before":before["text"], "after":payload.text,
                         "boardRevision":after["boardRevision"], "documentRevision":after["documentRevision"], "changed":payload.text != before["text"]})
            session.add(transfer); session.flush()
            return response(session, board, transfer)

    @routes.post("/{board_id}/prompt/{transfer_id}/undo")
    def undo(project_id: str, board_id: str, transfer_id: str):
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            board = owned_board(session, project_id, board_id)
            transfer = session.get(ProjectEvent, transfer_id)
            if not transfer or transfer.project_id != project_id or transfer.entity_id != board_id or transfer.event_type != "canvas.prompt_applied":
                raise HTTPException(404, "Prompt transfer does not belong to this board")
            prior = session.scalar(select(ProjectEvent.id).where(ProjectEvent.project_id == project_id, ProjectEvent.event_type == "canvas.prompt_undone", ProjectEvent.payload["transferId"].as_string() == transfer_id))
            if prior: return response(session, board, transfer, True)
            current = target_view(session, board); saved = transfer.payload
            if board.archived or current["boardRevision"] != saved["boardRevision"] or current["documentRevision"] != saved["documentRevision"] or current["destination"]["key"] != saved["destination"] or current["text"] != saved["after"]:
                raise HTTPException(409, "This board changed after the transfer. Undo cannot overwrite its newer edits.")
            if saved["changed"]: write_prompt(session, board, saved["before"])
            add_event(session, project_id, "canvas.prompt_undone", "board", board_id, {"transferId":transfer_id})
            return response(session, board, transfer, True)

    return routes
