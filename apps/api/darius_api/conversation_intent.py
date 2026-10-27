"""Resolve explicit production targets before model planning, within one project."""
import re
from fastapi import HTTPException
from .media_intent import is_media_request, output_kind, requested_count, draft_only, normalized


def resolve_production_target(context, text):
    text = normalized(text)
    if not is_media_request(text) or draft_only(text):
        return
    if not 1 <= requested_count(text) <= 6:
        raise HTTPException(422, "Please request between one and six outputs at a time.")
    memory = dict(context.get("project_memory") or {})
    scenes, shots = context.get("scenes", []), context.get("shots", [])
    scene_match = re.search(r"\bscene\s*(?:number\s*|#\s*)?(\d+)\b", text, re.I)
    shot_match = re.search(r"\bshot\s*(?:number\s*|#\s*)?(\d+)\b", text, re.I)
    scene_numbers = set(re.findall(r"\bscene\s*(?:number\s*|#\s*)?(\d+)\b", text, re.I))
    shot_numbers = set(re.findall(r"\bshot\s*(?:number\s*|#\s*)?(\d+)\b", text, re.I))
    if len(scene_numbers) > 1 or len(shot_numbers) > 1:
        # A multi-target request must not be narrowed to its first shot.
        memory["scene_id"], memory["shot_id"] = None, None
        scene_match = shot_match = None
    def proposed(kind, number):
        # Chat-only shot lists are valid creative context too; a saved bible
        # record is not required before generating a proposed shot.
        return any(item.get("role") == "assistant" and re.search(r"\b" + kind + r"\s*#?\s*" + str(number) + r"\b", item.get("content", ""), re.I)
                   for item in context.get("messages", [])[-12:])
    scene = None
    if scene_match:
        matches = [item for item in scenes if item.get("number") == int(scene_match[1])]
        if len(matches) != 1 and not (not matches and proposed("scene", int(scene_match[1]))):
            raise HTTPException(422, "Which scene do you mean? Choose a scene in Project context or give its saved scene number.")
        scene = matches[0] if matches else None
        if not scene:
            memory["scene_id"], memory["shot_id"] = None, None
    shot = None
    if shot_match:
        candidates = [item for item in shots if item.get("number") == int(shot_match[1])]
        scene_id = scene["id"] if scene else memory.get("scene_id")
        if scene_id:
            candidates = [item for item in candidates if item.get("scene_id") == scene_id]
        if len(candidates) != 1 and not (not candidates and proposed("shot", int(shot_match[1]))):
            raise HTTPException(422, f"Which scene contains shot {int(shot_match[1])}? Give the scene number or choose it in Project context.")
        if candidates:
            shot = candidates[0]
            scene = next((item for item in scenes if item["id"] == shot["scene_id"]), None)
            memory["shot_id"], memory["scene_id"] = shot["id"], shot["scene_id"]
            context["shots"] = [shot]
    elif scene:
        memory["scene_id"], memory["shot_id"] = scene["id"], None
        context["shots"] = [item for item in shots if item.get("scene_id") == scene["id"]]
    if scene:
        context["scenes"] = [scene]
    # Names explicitly spoken now override older character focus, without
    # combining unrelated project characters into the requested shot.
    subjects = [item for item in context.get("characters", []) if item.get("name") and
                re.search(r"(?<!\w)" + re.escape(item["name"]) + r"(?!\w)", text, re.I)]
    if len(subjects) == 1:
        memory["character_id"] = subjects[0]["id"]
    context["project_memory"] = memory
    context["resolved_intent"] = {"version": 1, "output_kind": output_kind(text), "output_count": requested_count(text),
        "scene": scene, "shot": shot, "subject_ids": [item["id"] for item in subjects],
        "reference_asset_ids": list(context.get("attached_asset_ids") or [])}


def needs_conversation_reference(text):
    return bool(re.search(r"\b(?:this|that|previous|last|attached|reference)\s+(?:image|picture|photo|result)\b|\b(?:animate|edit|retouch|upscale|enlarge)\s+(?:it|this|that|her|him|them)\b", text, re.I))
