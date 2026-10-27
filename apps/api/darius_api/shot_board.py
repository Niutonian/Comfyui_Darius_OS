"""Project-scoped production links without changing asset ownership."""
from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from .database import Asset, Job, Project, Scene, Shot, ShotProduction
from .schemas import AssetView, ShotView
from .assistant_context import project_memory


class ShotProductionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_asset_ids: list[str] | None = Field(default=None, max_length=4)
    take_asset_ids: list[str] | None = Field(default=None, max_length=100)
    selected_asset_id: str | None = None
    status: str | None = None


def production_context(session, project_id):
    memory = project_memory(session, project_id)
    shot = session.get(Shot, memory["shot_id"]) if memory["shot_id"] else None
    scene = session.get(Scene, shot.scene_id) if shot else None
    return {"shot_id": shot.id, "scene_id": scene.id} if scene and scene.project_id == project_id else {}


def board(session, project_id):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project does not exist")
    assets = {asset.id: asset for asset in session.scalars(select(Asset).where(Asset.project_id == project_id, Asset.role != "derivative"))}
    jobs = list(session.scalars(select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())))
    links = {link.shot_id: link.links_json for link in session.scalars(select(ShotProduction).join(Shot, Shot.id == ShotProduction.shot_id).join(Scene, Scene.id == Shot.scene_id).where(Scene.project_id == project_id))}
    rows = []
    for shot, scene in session.execute(select(Shot, Scene).join(Scene, Scene.id == Shot.scene_id).where(Scene.project_id == project_id).order_by(Scene.number, Shot.number)):
        saved = links.get(shot.id, {})
        associated = [job for job in jobs if job.input_payload.get("production_context", {}).get("shot_id") == shot.id]
        take_ids = list(dict.fromkeys([*saved.get("take_asset_ids", []), *[asset.id for asset in assets.values() if asset.shot_id == shot.id and asset.role != "reference"], *[aid for job in associated for aid in job.output_asset_ids], *([shot.selected_asset_id] if shot.selected_asset_id else [])]))
        rows.append({
            "shot": ShotView.model_validate(shot).model_dump(mode="json"),
            "scene_title": scene.title, "scene_number": scene.number,
            "references": [AssetView.model_validate(assets[aid]).model_dump(mode="json") for aid in saved.get("reference_asset_ids", []) if aid in assets and assets[aid].kind == "image"],
            "takes": [AssetView.model_validate(assets[aid]).model_dump(mode="json") for aid in take_ids if aid in assets and assets[aid].kind in {"image", "video"}],
            "jobs": [{"id": job.id, "status": job.status, "progress": job.progress, "status_message": job.status_message} for job in associated[:20]],
        })
    return rows


def update_production(session, project_id, shot_id, payload):
    project = session.get(Project, project_id)
    shot = session.get(Shot, shot_id)
    scene = session.get(Scene, shot.scene_id) if shot else None
    if not project or not scene or scene.project_id != project_id:
        raise HTTPException(404, "shot does not belong to this project")
    saved = session.get(ShotProduction, shot_id)
    links = dict(saved.links_json) if saved else {}
    for field in ("reference_asset_ids", "take_asset_ids"):
        values = getattr(payload, field)
        if values is None:
            continue
        for aid in values:
            asset = session.get(Asset, aid)
            if not asset or asset.project_id != project_id or asset.role == "derivative" or asset.kind not in ({"image"} if field == "reference_asset_ids" else {"image", "video"}):
                raise HTTPException(422, "Production media must belong to this project and have a supported type")
        links[field] = list(dict.fromkeys(values))
    if "selected_asset_id" in payload.model_fields_set:
        aid = payload.selected_asset_id
        asset = session.get(Asset, aid) if aid else None
        if aid and (not asset or asset.project_id != project_id or asset.kind not in {"image", "video"} or asset.role == "derivative"):
            raise HTTPException(422, "Selected take must be image or video media in this project")
        shot.selected_asset_id = aid
        if aid:
            links["take_asset_ids"] = list(dict.fromkeys([*links.get("take_asset_ids", []), aid]))
    if payload.status is not None:
        if payload.status not in {"planned", "ready", "generated", "selected", "complete"}:
            raise HTTPException(422, "Unsupported shot status")
        shot.status = payload.status
    if shot.status in {"selected", "complete"} and not shot.selected_asset_id:
        raise HTTPException(422, "Choose a take before marking the shot selected or complete")
    if saved:
        saved.links_json = links
    else:
        session.add(ShotProduction(shot_id=shot_id, links_json=links))
    return shot
