"""Deterministic spoken gallery/playback controls, scoped to the requesting device."""
import re
from types import SimpleNamespace
from sqlalchemy import select
from .database import Asset
from .providers import ProviderError

def media_command(text):
    from .command_router import route_command
    result = route_command(text)
    return result if result and result["action"] != "open" else None


def visible_context(session, settings, project_id, source):
    from .asset_presentation import presentation_action
    value = source.metadata_json.get("presentation_context")
    if not isinstance(value, dict):
        return None
    ids, index = value.get("asset_ids"), value.get("index")
    receipt = presentation_action(session, settings, project_id, "select", ids, index=index)
    return {"ids": receipt["asset_ids"], "index": index, "mode": value.get("mode")}


def quick_media_control(session, settings, conversation, source, messages):
    from .asset_presentation import presentation_action, quick_presentation
    from .assistant_assets import managed_asset_path
    command = media_command(source.content)
    if not command:
        return None
    project_id, action = conversation.project_id, command["action"]
    def answer(reply, receipts=None):
        return {"reply": reply, "actions": receipts or []}
    try:
        if action == "clarify":
            return answer("That could mean more than one media command. Please name one action or select a gallery number.")
        if action == "gallery":
            statement = select(Asset).where(Asset.project_id == project_id, Asset.role != "derivative", Asset.kind.in_([command["kind"]] if command["kind"] else ["image", "video"]))
            candidates = session.scalars(statement.order_by(Asset.created_at.desc(), Asset.id).limit(48))
            ids = []
            for asset in candidates:
                try:
                    managed_asset_path(asset, settings)
                    ids.append(asset.id)
                except ProviderError:
                    continue
            if not ids:
                return answer("This project has no available saved media for that gallery yet.")
            return answer("Opening the gallery, newest first. Say open image three, select a name, or play video two. The numbers match the cards on your screen.", [presentation_action(session, settings, project_id, "gallery", ids)])
        if action == "close":
            return answer("Closing the media view.", [presentation_action(session, settings, project_id, "close")])
        if action == "play_target":
            result = quick_presentation(session, settings, conversation, SimpleNamespace(content=command["text"], id=source.id, metadata_json=source.metadata_json), messages)
            if not result:
                return answer("Name a saved video or ask me to play the latest video.")
            receipts = []
            for receipt in result["actions"]:
                if receipt["action"] == "open":
                    receipts.append(presentation_action(session, settings, project_id, "open", receipt["asset_ids"], autoplay=True))
            return answer("Opening the video and requesting playback. If your browser blocks it, tap Play." if receipts else result["reply"], receipts)
        context = visible_context(session, settings, project_id, source)
        if not context:
            if command.get("bare") or action in {"next", "previous"}:
                return None
            if action == "play":
                return quick_media_control(session, settings, conversation, SimpleNamespace(content="Open the video and play it", id=source.id, metadata_json=source.metadata_json), messages)
            return answer("Open the gallery or a video on this device first, then tell me which item to control.")
        ids, index = context["ids"], context["index"]
        if action == "back":
            return answer("Back to the gallery.", [presentation_action(session, settings, project_id, "gallery", ids)])
        if action in {"select", "select_name", "next", "previous"}:
            if action == "select_name":
                name = re.sub(r"[^\w]+", " ", command["name"]).strip().casefold()
                matches = []
                for position, key in enumerate(ids):
                    asset = session.get(Asset, key)
                    label = asset.metadata_json.get("display_name") or asset.metadata_json.get("original_filename") or ""
                    if name and name in re.sub(r"[^\w]+", " ", label).strip().casefold():
                        matches.append(position)
                if len(matches) != 1:
                    return answer("I couldn't pick a unique item with that name. Please say its number from the gallery.")
                index = matches[0]
            elif action == "select":
                index = command["index"]
            else:
                index += 1 if action == "next" else -1
            if not 0 <= index < len(ids):
                return answer(f"Choose an item from 1 to {len(ids)} in the current gallery.")
            receipt = presentation_action(session, settings, project_id, "select", ids, index=index, autoplay=command.get("autoplay", False))
            return answer(f"Opening item {index + 1}." + (" Requesting playback; tap Play if your browser blocks it." if command.get("autoplay") else ""), [receipt])
        asset = session.get(Asset, ids[index])
        if context["mode"] != "viewer" or asset.kind not in {"video", "audio"}:
            return answer("Open a video from the gallery first, then ask me to play, pause, stop, or seek.")
        receipt = presentation_action(session, settings, project_id, action, [asset.id], seconds=command.get("seconds"))
        replies = {"play": "Requesting playback. Tap Play if your browser blocks it.", "pause": "Pausing the video.", "stop": "Stopping the video and returning to the start.", "restart": "Restarting playback.", "mute": "Muting the video.", "unmute": "Unmuting the video.", "seek": "Moving through the video."}
        return answer(replies[action], [receipt])
    except ProviderError:
        return answer("That selection or original media is unavailable in this project. Open the gallery again to refresh it.")
