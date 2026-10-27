"""User-editable memory and project ownership checks for assistant context."""
from pydantic import BaseModel, Field, ConfigDict
from fastapi import HTTPException
from sqlalchemy import select
from .database import AssistantMemory, Asset, Character, Scene, Shot, Conversation, Message
from .trusted_workflows import WorkflowPreferences


class AssistantContextUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str = Field(default="", max_length=6000)
    character_id: str | None = None
    scene_id: str | None = None
    shot_id: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=4)
    workflow_preferences: WorkflowPreferences = Field(default_factory=WorkflowPreferences)


def scoped_asset_ids(session, project_id, values):
    if not isinstance(values, list):
        return []
    ids = [value for value in values if isinstance(value, str)][:20]
    owned = set(session.scalars(select(Asset.id).where(Asset.project_id == project_id, Asset.id.in_(ids))))
    return list(dict.fromkeys(value for value in ids if value in owned))


def validate_memory(session, project_id, body):
    for field, model in (("character_id", Character), ("scene_id", Scene)):
        value = getattr(body, field)
        record = session.get(model, value) if value else None
        if value and (not record or record.project_id != project_id):
            raise HTTPException(422, f"{field} does not belong to this project")
    if body.shot_id:
        shot = session.get(Shot, body.shot_id)
        scene = session.get(Scene, shot.scene_id) if shot else None
        if not shot or not scene or scene.project_id != project_id or (body.scene_id and body.scene_id != scene.id):
            raise HTTPException(422, "shot_id does not belong to the selected project and scene")
        body.scene_id = scene.id
    if len(scoped_asset_ids(session, project_id, body.reference_asset_ids)) != len(set(body.reference_asset_ids)):
        raise HTTPException(422, "Reference image does not belong to this project")
    for asset_id in body.reference_asset_ids:
        if session.get(Asset, asset_id).kind != "image":
            raise HTTPException(422, "Pinned references must be images")
    return body.model_dump()


def project_memory(session, project_id):
    saved = session.get(AssistantMemory, project_id)
    data = AssistantContextUpdate.model_validate(saved.context_json if saved else {}).model_dump()
    data["reference_asset_ids"] = scoped_asset_ids(session, project_id, data["reference_asset_ids"])
    for field, model in (("character_id", Character), ("scene_id", Scene)):
        record = session.get(model, data[field]) if data[field] else None
        if not record or record.project_id != project_id:
            data[field] = None
    shot = session.get(Shot, data["shot_id"]) if data["shot_id"] else None
    if not shot or shot.scene_id != data["scene_id"]:
        data["shot_id"] = None
    return data


def workflow_available(session, project_id, contract):
    owner = getattr(contract, "project_id", None)
    if owner:
        return owner == project_id
    sources = contract.source_asset_ids
    if sources:
        return bool(project_id) and all((asset := session.get(Asset, asset_id)) is not None and asset.project_id == project_id for asset_id in sources)
    if contract.id.startswith("assistant-"):
        return bool(project_id) and session.scalar(select(Message.id).join(Conversation, Message.conversation_id == Conversation.id).where(
            Conversation.project_id == project_id, Message.metadata_json["workflow_id"].as_string() == contract.id).limit(1)) is not None
    return True
