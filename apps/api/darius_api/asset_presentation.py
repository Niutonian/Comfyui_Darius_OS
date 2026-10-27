"""Bounded client presentation requests: no rendering, pixel analysis, or URLs."""
import re
from uuid import uuid4
from sqlalchemy import or_, select
from .database import Asset, GenerationRecord, Job


def presentation_action(session, settings, project_id, action, asset_ids=None, *, index=None, autoplay=False, seconds=None):
    from .providers import ProviderError
    from .assistant_assets import managed_asset_path
    if not isinstance(action, str) or action not in {"open", "gallery", "select", "back", "close", "next", "previous", "play", "pause", "stop", "restart", "mute", "unmute", "seek"}:
        raise ProviderError("Choose a supported gallery or media control")
    ids = asset_ids or []
    if not isinstance(ids, list) or any(not isinstance(key, str) or not key or len(key) > 100 for key in ids):
        raise ProviderError("Use active-project asset IDs, not URLs or paths")
    ids = list(dict.fromkeys(ids))
    if action in {"open", "gallery", "select", "play", "pause", "stop", "restart", "mute", "unmute", "seek"}:
        limit = 48 if action in {"gallery", "select"} else 12 if action == "open" else 1
        if not 1 <= len(ids) <= limit:
            raise ProviderError("Choose a bounded list of original project assets to display")
        for key in ids:
            asset = session.get(Asset, key)
            if not asset or asset.project_id != project_id or asset.kind not in {"image", "video", "audio"} or asset.role == "derivative":
                raise ProviderError("The original asset is unavailable in this project")
            managed_asset_path(asset, settings)
            if action in {"play", "pause", "stop", "restart", "mute", "unmute", "seek"} and asset.kind not in {"video", "audio"}:
                raise ProviderError("Playback controls require a video or audio asset")
    elif ids:
        raise ProviderError("Viewer navigation does not accept asset IDs")
    receipt = {"id": uuid4().hex, "action": action, "asset_ids": ids, "project_id": project_id}
    if action == "select":
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(ids):
            raise ProviderError("Select a numbered item in the visible gallery")
        receipt["index"] = index
    if not isinstance(autoplay, bool) or autoplay and action not in {"open", "select"}:
        raise ProviderError("Playback can only be requested for an opened selection")
    if autoplay:
        if session.get(Asset, ids[index if action == "select" else 0]).kind not in {"video", "audio"}:
            raise ProviderError("Only videos or audio can be played")
        receipt["autoplay"] = True
    if action == "seek":
        if isinstance(seconds, bool) or not isinstance(seconds, (float, int)) or not -600 <= seconds <= 600:
            raise ProviderError("Seek by up to 600 seconds at a time")
        receipt["seconds"] = seconds
    return receipt


def command(text):
    from .command_router import route_command
    result = route_command(text)
    if result and result["action"] in {"open", "close", "next", "previous"}:
        return result["action"], result.get("target", "")
    return None


def quick_presentation(session, settings, conversation, source, messages):
    """Common viewer controls bypass the planner, not any media ownership check."""
    from .media_controls import quick_media_control
    control = quick_media_control(session, settings, conversation, source, messages)
    if control is not None:
        return control
    parsed = command(source.content)
    if not parsed:
        return None
    action, target = parsed
    from .providers import ProviderError
    if action != "open":
        return {"reply": {"close": "Closing the full-size preview.", "next": "Moving to the next asset in the preview.", "previous": "Moving to the previous asset in the preview."}[action],
                "actions": [presentation_action(session, settings, conversation.project_id, action)]}
    kind = "video" if re.search(r"\b(videos?|clips?)\b", target, re.I) else "image" if re.search(r"\b(images?|pictures?|photos?)\b", target, re.I) else None
    ids = [key.lower() for key in re.findall(r"\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b", target, re.I)]
    latest = bool(re.search(r"\b(latest|last|newest|recent)\b", target, re.I))
    generated = bool(re.search(r"\b(generated|rendered|finished|completed|renders?|results?)\b", target, re.I))
    if generated:
        target = re.sub(r"\b(was|is|has|been|just|you|have)\b", "", target, flags=re.I)
    # Named assets search only the active project's saved names/prompts.
    query = re.sub(r"\b(?:me|us|the|a|an|my|our|this|that|it|them|these|those|latest|last|newest|recent|generated|finished|completed|rendered|renders?|original|image|images|picture|pictures|photo|photos|video|videos|clip|clips|asset|assets|result|results|media|in|at|as|to|on|of|with|here|above|again|larger|bigger|full|size|fullsize|screen|fullscreen|please|inside|conversation)\b", "", target, flags=re.I)
    words = re.findall(r"[\w'-]+", query)[:8] if not ids else []
    if not ids and words and not latest:
        statement = select(Asset).outerjoin(GenerationRecord, Asset.workflow_run_id == GenerationRecord.job_id).where(Asset.project_id == conversation.project_id, Asset.role != "derivative")
        for word in words:
            term = "%" + word.replace("%", "\\%").replace("_", "\\_") + "%"
            statement = statement.where(or_(Asset.metadata_json["display_name"].as_string().ilike(term, escape="\\"), Asset.metadata_json["original_filename"].as_string().ilike(term, escape="\\"), GenerationRecord.prompt.ilike(term, escape="\\")))
        if kind:
            statement = statement.where(Asset.kind == kind)
        ids = [asset.id for asset in session.scalars(statement.order_by(Asset.created_at.desc()).limit(12))]
    elif not ids:
        def safe_ids(value):
            return list(dict.fromkeys(key for key in value if isinstance(key, str) and 0 < len(key) <= 100))[:12] if isinstance(value, list) else []
        ids = safe_ids(source.metadata_json.get("asset_ids", [])) if not latest and not generated else []
        for message in messages:
            if ids or message.id == source.id:
                continue
            metadata = message.metadata_json
            candidates = []
            if message.role == "assistant" and not generated:
                receipts = metadata.get("presentation_actions", [])
                for receipt in reversed(receipts if isinstance(receipts, list) else []):
                    if isinstance(receipt, dict) and receipt.get("action") == "open":
                        candidates = safe_ids(receipt.get("asset_ids", [])); break
                candidates = candidates or safe_ids(metadata.get("viewed_asset_ids", []))
            job_ids = safe_ids(metadata.get("job_ids")) or safe_ids(metadata.get("local_render_job_ids")) or safe_ids([metadata.get("job_id") or metadata.get("local_render_job_id")])
            if not candidates and job_ids:
                for job_id in job_ids[:12]:
                    job = session.get(Job, job_id)
                    if job and job.project_id == conversation.project_id:
                        candidates.extend(job.output_asset_ids or [])
                if not candidates:
                    return {"reply": "That render has no saved output yet. Wait for it to finish, then ask me to open it.", "actions": []}
            if not candidates and message.role == "user" and not generated:
                candidates = safe_ids(metadata.get("asset_ids", []))
            ids = [key for key in dict.fromkeys(candidates) if (asset := session.get(Asset, key)) and asset.project_id == conversation.project_id and asset.role != "derivative" and (not kind or asset.kind == kind)]
        if not ids and latest:
            statement = select(Asset).where(Asset.project_id == conversation.project_id, Asset.role != "derivative", Asset.kind.in_([kind] if kind else ["image", "video", "audio"]))
            if generated:
                statement = statement.where(Asset.workflow_run_id.is_not(None))
            asset = session.scalar(statement.order_by(Asset.created_at.desc()).limit(1))
            ids = [asset.id] if asset else []
    if not ids:
        return {"reply": "I couldn't identify that saved asset. Attach it, name it, or ask me to open the latest image or video.", "actions": []}
    try:
        receipt = presentation_action(session, settings, conversation.project_id, "open", ids[:12])
    except ProviderError:
        return {"reply": "That original asset is unavailable in this project or its media file is missing. No preview was opened.", "actions": []}
    return {"reply": "Opening the original asset full size." if len(receipt["asset_ids"]) == 1 else "Opening the original assets full size. Use next and previous to browse them.", "actions": [receipt]}
