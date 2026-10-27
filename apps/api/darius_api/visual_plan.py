"""Validated, request-scoped shot briefs shared by every planner transport."""
import json
import re


def response_object(response):
    # Reasoning items can precede the message; output[0] is not the answer.
    if response.get("status") == "incomplete":
        reason = (response.get("incomplete_details") or {}).get("reason", "unknown")
        raise ValueError(f"Visual brief response incomplete ({reason})")
    parts = []
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") in {"reasoning", "function_call"}:
            continue
        for part in item.get("content", []) or []:
            if isinstance(part, dict) and part.get("type") == "refusal":
                raise ValueError("Visual brief was declined; revise the creative request")
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
    text = "".join(parts).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Visual brief must be a JSON object")
    return value


SHOT_SCHEMA = {"type": "object", "properties": {
    "prompt": {"type": "string"},
    "subject_ids": {"type": "array", "items": {"type": "string"}},
    "reference_asset_ids": {"type": "array", "items": {"type": "string"}},
}, "required": ["prompt", "subject_ids", "reference_asset_ids"], "additionalProperties": False}


def input_references(references, context):
    """Viewed context is not automatically a requested physical recipe input.

    Only a server-routed text-only request with no explicit/pinned images can
    discard model-suggested bindings. Explicit references must still be bound
    or rejected by preflight, never silently removed.
    """
    route = context.get("workflow_route")
    if (isinstance(route, dict) and route.get("purpose") in {"text-to-image", "text-to-video", "character-sheet"}
            and not route.get("reference_asset_ids") and not context.get("attached_asset_ids")
            and not (context.get("project_memory") or {}).get("reference_asset_ids")):
        return []
    return list(references)


def normalize_plan(answer, context, request):
    from .media_intent import requested_count
    count = requested_count(request)
    shots = answer.get("shots") or []
    if not isinstance(shots, list) or len(shots) > 6:
        raise ValueError("A visual plan must contain at most six shot briefs")
    if not shots:
        shots = [{"prompt": answer["generation_prompt"], "subject_ids": [], "reference_asset_ids": []}]
    if len(shots) > 1 and len(shots) != count:
        raise ValueError(f"The request authorizes {count} outputs; provide exactly that many shot briefs")
    characters = {c["id"]: c for c in context.get("characters", []) if isinstance(c, dict) and c.get("id")}
    assets = {a["id"] for a in context.get("assets", []) if isinstance(a, dict) and a.get("id")}
    assets.update(context.get("attached_asset_ids") or [])
    assets.update((context.get("project_memory") or {}).get("reference_asset_ids") or [])
    for character in characters.values():
        assets.update(character.get("approved_reference_asset_ids") or [])
    for evidence in context.get("reference_evidence", []):
        result = evidence.get("result") or {}
        if isinstance(result.get("asset_id"), str):
            assets.add(result["asset_id"])
        assets.update(result.get("viewed_asset_ids") or [])
        for asset in result.get("assets", []):
            if isinstance(asset, dict) and isinstance(asset.get("id"), str):
                assets.add(asset["id"])
    result = []
    required = (context.get("resolved_intent") or {}).get("subject_ids", [])
    for key in required:
        character = characters.get(key)
        if character and not any(isinstance(shot, dict) and re.search(r"(?<!\w)" + re.escape(character["name"]) + r"(?!\w)", str(shot.get("prompt", "")), re.I) for shot in shots):
            raise ValueError(f"Keep the explicitly requested character {character['name']} in the visual description")
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            raise ValueError("Each shot needs its own visual description")
        prompt = shot.get("prompt")
        if not isinstance(prompt, str) or not 10 <= len(prompt.strip()) <= 20000:
            raise ValueError("Each shot needs a visual description of 10–20000 characters")
        if prompt.strip().casefold() == request.strip().casefold() or re.match(r"(?:could|can|would)\s+you\s+(?:please\s+)?(?:generate|render|create|make)\b", prompt, re.I):
            raise ValueError("A workflow command cannot be used as a shot description")
        subjects, references = shot.get("subject_ids", []), shot.get("reference_asset_ids", [])
        if not isinstance(subjects, list) or any(not isinstance(v, str) or v not in characters for v in subjects):
            raise ValueError("Shot subjects must identify characters in the active project")
        for key in required:
            character = characters.get(key)
            if character and key not in subjects and re.search(r"(?<!\w)" + re.escape(character["name"]) + r"(?!\w)", prompt, re.I):
                subjects = [*subjects, key]
        if not isinstance(references, list) or any(not isinstance(v, str) or v not in assets for v in references):
            raise ValueError("Shot references must identify images in the active project context")
        context_references = list(dict.fromkeys(references))
        references = input_references(references, context)
        # Store each subject separately; do not merge appearance/reference identities.
        identities = [{"id": v, "name": characters[v].get("name"),
                       "canonical_prompt": characters[v].get("canonical_prompt", ""),
                       "reference_asset_ids": characters[v].get("approved_reference_asset_ids", [])}
                      for v in dict.fromkeys(subjects)]
        result.append({"id": f"shot-{index + 1}", "prompt": prompt.strip(),
                       "subject_ids": list(dict.fromkeys(subjects)), "subjects": identities,
                       "reference_asset_ids": list(dict.fromkeys(references)),
                       **({"context_reference_asset_ids": context_references} if context_references and not references else {})})
    return {"version": 1, "request": request, "shots": result, "output_count": count}


def cached_plan(context):
    for key in ("_visual_brief", "_local_visual_brief", "_opencode_visual_brief"):
        saved = context.get(key)
        if isinstance(saved, dict) and isinstance(saved.get("plan"), dict):
            return saved["plan"]
    return None
