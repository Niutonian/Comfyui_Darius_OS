"""Project-owned recipes and bounded routing, before any model call."""
import re
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .database import AssistantMemory, Asset, Job, GlobalWorkflowPreference
from .media_intent import is_media_request, output_kind, resolve_request

Purpose = Literal["text-to-image", "image-to-image", "image-upscale", "text-to-video", "image-to-video", "video-to-video", "character-sheet", "face-consistency", "lip-sync"]


class TrustedWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: str = Field(min_length=1, max_length=300)
    purpose: Purpose
    is_default: bool = False


class WorkflowPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    entries: list[TrustedWorkflow] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def unique_recipes(self):
        keys = [(entry.workflow_id, entry.purpose) for entry in self.entries]
        defaults = [entry.purpose for entry in self.entries if entry.is_default]
        if len(keys) != len(set(keys)) or len(defaults) != len(set(defaults)):
            raise ValueError("Use unique recipes and one default per task type")
        if self.enabled and not self.entries:
            raise ValueError("Choose at least one trusted workflow before enabling automatic selection")
        return self


def preferences(session, project_id):
    saved = session.get(AssistantMemory, project_id)
    return WorkflowPreferences.model_validate((saved.context_json or {}).get("workflow_preferences", {}) if saved else {})


def global_preferences(session):
    saved = session.get(GlobalWorkflowPreference, "default")
    return WorkflowPreferences.model_validate(saved.preferences_json if saved else {})


def compatible(contract, purpose):
    assignable = getattr(contract, "assignable_purposes", None)
    if assignable is not None:
        return purpose in assignable
    if purpose == "character-sheet":
        return contract.output.kind == "image" and contract.capability in {"text-to-image", "character-sheet"}
    if purpose == "face-consistency":
        return contract.output.kind == "image" and (contract.capability in {"image-to-image", "face-consistency"} or any(item.type == "asset:image" for item in contract.required_inputs))
    if purpose == "image-upscale":
        return contract.execution_provider == "local-comfyui" and contract.output.kind == "image" and (contract.capability == "image-to-image" or any(item.type == "asset:image" for item in contract.required_inputs))
    return contract.capability == purpose


def available_recipes(session, project_id, registry, settings=None):
    from .assistant_context import workflow_available
    if settings is not None:
        from .base_recipes import recipes
        return recipes(settings, registry)
    return {w.id: w for w in registry.enabled() if workflow_available(session, project_id, w)}


def validate_preferences(session, project_id, registry, value, settings=None):
    available = available_recipes(session, project_id, registry, settings)
    for entry in value.entries:
        workflow = available.get(entry.workflow_id)
        if not workflow:
            raise HTTPException(422, f"Workflow {entry.workflow_id} is unavailable in this project")
        if not compatible(workflow, entry.purpose):
            raise HTTPException(422, f"{workflow.name} is incompatible with {entry.purpose}")
    return available


def summary(workflow):
    """Never include graphs, node mappings, sample prompts, or bound asset IDs."""
    return {
        "id": workflow.id, "name": workflow.name[:160], "capability": workflow.capability,
        "execution_provider": workflow.execution_provider, "output": workflow.output.model_dump(),
        "required_inputs": [{"key": item.key, "type": item.type, "required": item.required}
                            for item in workflow.required_inputs if item.required],
    }


def _workflow_words(value):
    value = re.sub(r"\bmini[\s_-]+max\b", "minimax", value, flags=re.I)
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _named_recipe(text, available):
    """Resolve complete names or a unique distinctive spoken workflow alias."""
    if not re.search(r"\b(use|using|with|select|choose)\b", text, re.I):
        return None
    words = " " + _workflow_words(text) + " "
    matches, aliases = [], []
    generic = {"darius", "workflow", "image", "images", "video", "videos", "generate", "generation",
               "text", "to", "t2i", "i2i", "t2v", "i2v", "txt2img", "img2img", "core", "base", "api"}
    families = {"qwen", "flux", "minimax", "krea", "ideogram", "ltx", "wan"}
    for recipe in available.values():
        if recipe.output.kind != output_kind(text):
            continue
        name = re.sub(r"^darius[\s_-]+", "", recipe.name, flags=re.I)
        name = re.sub(r"[\s_-]+workflow$", "", name, flags=re.I)
        name = _workflow_words(name)
        direct_name = (len(name.split()) >= 2 or re.search(
            rf"\b(?:use|using|select|choose)\s+(?:the\s+)?{re.escape(name)}\b|\bwith\s+(?:the\s+)?{re.escape(name)}\s*[.!?,]*\s*$", text, re.I))
        if name and direct_name and " " + name + " " in words:
            matches.append(recipe.id)
        distinctive = [word for word in name.split() if word not in generic and word not in families
                       and not word.isdigit() and not re.fullmatch(r"[a-f0-9]{8,}", word)]
        for alias in distinctive:
            # "Moss" in a scene is not an execution instruction. A short name
            # must follow a selector, or finish a "with Moss [workflow]" clause.
            selector = rf"\b(?:use|using|select|choose)\s+(?:the\s+)?{re.escape(alias)}\b"
            ending = rf"\bwith\s+(?:the\s+)?{re.escape(alias)}(?:\s+workflow)?\s*[.!?,]*\s*$"
            if re.search(selector, text, re.I) or re.search(ending, text, re.I):
                aliases.append(recipe.id)
                break
    choices = list(dict.fromkeys(matches or aliases))
    if len(choices) > 1:
        raise HTTPException(422, "That workflow name matches more than one recipe: " + ", ".join(available[key].name for key in choices[:6]) + ". Choose the full workflow name; nothing was generated.")
    return choices[0] if choices else None


def _conversation_image(session, project_id, context):
    """Only the current conversation supplies implicit media, never project-wide jobs."""
    for item in reversed(context.get("messages", [])[-40:]):
        if item.get("role") == "assistant" and (item.get("presentation_asset_ids") or item.get("viewed_asset_ids")):
            ids = list(dict.fromkeys(item.get("presentation_asset_ids") or item.get("viewed_asset_ids")))
        elif item.get("role") == "assistant" and item.get("job_id"):
            job_ids = item.get("job_ids") or (item.get("task") or {}).get("job_ids") or [item["job_id"]]
            if len(set(job_ids)) > 1:
                raise HTTPException(422, "The previous render has several outputs. Attach the specific image to animate.")
            job = session.get(Job, item["job_id"])
            if not job or job.project_id != project_id:
                raise HTTPException(422, "The referenced render is unavailable in this project. Attach the image to animate.")
            ids = list(dict.fromkeys(job.output_asset_ids or []))
            if not ids:
                raise HTTPException(422, "The referenced render has no output yet. Wait for it to finish or attach the image to use.")
        elif item.get("role") == "user" and (item.get("asset_ids") or item.get("reference_asset_ids")):
            ids = list(dict.fromkeys([*item.get("asset_ids", []), *item.get("reference_asset_ids", [])]))
        else:
            continue
        assets = [session.get(Asset, key) for key in ids]
        if any(not asset or asset.project_id != project_id for asset in assets):
            raise HTTPException(422, "The referenced image is unavailable in this project. Attach the image to animate.")
        images = [asset.id for asset in assets if asset.kind == "image"]
        if len(images) != 1:
            raise HTTPException(422, "The previous result does not identify one image. Attach the specific image to animate.")
        return images
    raise HTTPException(422, "I could not identify the image in this conversation. Attach the image to animate; workflow sample images will not be reused.")


def route_context(session, project_id, registry, context, request_text, settings=None):
    saved = preferences(session, project_id)
    global_saved = global_preferences(session)
    configured = saved.enabled or global_saved.enabled
    project_entries = saved.entries if saved.enabled else []
    overridden_purposes = {entry.purpose for entry in project_entries}
    inherited_entries = [entry for entry in global_saved.entries if entry.purpose not in overridden_purposes] if global_saved.enabled else []
    merged_entries = [*project_entries, *inherited_entries]
    text = resolve_request(request_text, context)
    if not configured and (settings is None or (not is_media_request(text) and not re.search(r"\bworkflows?\b", text, re.I))):
        return
    from .assistant_context import workflow_available
    available = available_recipes(session, project_id, registry, settings)
    trusted = ([entry for entry in merged_entries if entry.workflow_id in available] if configured else
               [TrustedWorkflow(workflow_id=w.id, purpose=purpose) for w in available.values()
                if w.execution_provider == "local-comfyui" or not is_media_request(text)
                for purpose in (w.capability, *([ "character-sheet" ] if w.capability == "text-to-image" else []))])
    explicit = context.get("preferred_workflow_id") or _named_recipe(text, available)
    # A user may explicitly reuse a project draft. It never becomes an automatic base.
    if explicit and explicit not in available:
        try:
            selected = registry.get(explicit)
            if workflow_available(session, project_id, selected):
                available[explicit] = selected
        except KeyError:
            pass
    allowed = {entry.workflow_id for entry in trusted}
    if explicit:
        if explicit not in available:
            raise HTTPException(422, "The explicitly selected workflow is unavailable in this project")
        allowed.add(explicit)
    context["workflows"] = [summary(available[key]) for key in sorted(allowed)]
    context["workflow_policy"] = {
        "enabled": True, "allowed_ids": sorted(allowed),
        "instruction": "Use these trusted templates. Inspect the selected workflow and prepare a copy with prompt/input overrides. Do not discover the full catalog or invent nodes. If required inputs are missing, ask for them. Do not switch workflows on failure. Explicit workflow selection overrides project mappings, which override global defaults for the same action.",
    }
    context["trusted_workflows"] = [entry.model_dump() for entry in trusted]
    if not is_media_request(text):
        return
    reference_ids = list(dict.fromkeys(context.get("attached_asset_ids", []) or context.get("project_memory", {}).get("reference_asset_ids", [])))
    from .conversation_intent import needs_conversation_reference
    previous_image = re.search(r"\b(this|that|previous|attached|reference)\s+(image|picture|photo)|\banimate\s+(it|this|that|her|him|them)\b", text, re.I)
    # Spoken subjects ('a video of this angel') are references too. A fresh
    # text-only request ('a video of an angel') must NOT inherit an old image.
    previous_image = previous_image or needs_conversation_reference(text) or (output_kind(text) == "video" and re.search(
        r"\b(?:of|from|using|with)\s+(?:(?:this|that)\b|the\s+(?:last|previous|generated|rendered)\b)", text, re.I))
    if not reference_ids and previous_image:
        reference_ids = _conversation_image(session, project_id, context)
        context["attached_asset_ids"] = reference_ids
    references = [asset for key in reference_ids if (asset := session.get(Asset, key)) and asset.project_id == project_id]
    image_reference = any(asset.kind == "image" for asset in references)
    video_reference = any(asset.kind == "video" for asset in references)
    if re.search(r"\blip[ -]?sync\b", text, re.I):
        purpose = "lip-sync"
    elif re.search(r"\bface[ -]?consistency\b", text, re.I):
        purpose = "face-consistency"
    elif output_kind(text) == "video":
        purpose = "video-to-video" if video_reference else "image-to-video" if image_reference else "text-to-video"
    elif re.search(r"\b(upscale|upscaling|enlarge|super.resolution)\b", text, re.I):
        purpose = "image-upscale"
    elif re.search(r"\bcharacter[ -]?sheet\b", text, re.I):
        purpose = "character-sheet"
    else:
        purpose = "image-to-image" if image_reference or re.search(r"\b(edit|retouch|img2img|image.to.image)\b", text, re.I) else "text-to-image"
    if explicit:
        selected = available[explicit]
        if selected.output.kind != output_kind(text) or not compatible(selected, purpose):
            raise HTTPException(422, "The selected workflow does not support this action. Choose a compatible image or video workflow in Trusted workflows.")
        source = "explicit"
    else:
        candidates = [entry for entry in trusted if entry.purpose == purpose and compatible(available[entry.workflow_id], purpose)]
        family = next((name for name in ("krea", "qwen", "flux", "ideogram", "minimax", "ltx", "wan")
                       if re.search(r"\b" + name + r"(?:\s*\d|\b)", _workflow_words(text), re.I)), None)
        if family:
            candidates = [entry for entry in candidates if family in (available[entry.workflow_id].name + " " + entry.workflow_id).lower()]
        candidates.sort(key=lambda entry: not entry.is_default)
        if configured and len(candidates) > 1 and not candidates[0].is_default:
            names = ", ".join(available[entry.workflow_id].name for entry in candidates[:4])
            raise HTTPException(422, "Which workflow should I use? " + names + ". Choose one, or set a default for this action in Trusted workflows.")
        if not candidates:
            if (purpose == "text-to-video" and not configured
                    and any(w.capability == "image-to-video" for w in available.values())
                    and not any(w.execution_provider == "local-comfyui" and w.capability == "text-to-video" for w in available.values())):
                raise HTTPException(422, "The available video bases need a source image; none is a text-to-video recipe"
                    + (f" matching {family}" if family else "")
                    + ". Attach an image or say 'animate this image' after an image render. For text-only video, add a text-to-video base to the default-workflow folder, Refresh workflows, and associate it with Generate video. No model tokens or render credits were used.")
            raise HTTPException(422, f"No {'matching ' + family + ' ' if family else ''}base recipe for {purpose}. Add the workflow to the default-workflow folder, click Refresh workflows in Create → Trusted workflows, and associate it with this action. No model tokens or render credits were used.")
        selected = available[candidates[0].workflow_id]
        chosen = candidates[0]
        if not configured:
            source = "defaults-folder"
        elif chosen.purpose in overridden_purposes:
            source = "project-default" if chosen.is_default else "trusted-list"
        else:
            source = "global-default" if chosen.is_default else "global-trusted-list"
    context["preferred_workflow_id"] = selected.id
    context["preferred_workflow"] = summary(selected)
    context["workflow_policy"]["allowed_ids"] = [selected.id]
    context["workflow_policy"]["purpose"] = purpose
    if selected.execution_provider == "bfl":
        context["workflow_policy"]["instruction"] = "The selected trusted workflow is a BFL cloud API operation, not a ComfyUI graph. Return its workflow_id and the resolved generation_prompt for review. Do not discover, inspect, or prepare a ComfyUI graph for it. Existing explicit approval and cloud billing checks apply."
    context["workflows"] = [summary(selected)]
    context["trusted_workflows"] = [entry.model_dump() for entry in trusted if entry.purpose == purpose][:8]
    context["workflow_route"] = {"workflow_id": selected.id, "name": selected.name, "purpose": purpose, "source": source,
                                "reference_asset_ids": [asset.id for asset in references if asset.kind == "image"]}
    if context.get("resolved_intent"):
        context["resolved_intent"]["reference_asset_ids"] = context["workflow_route"]["reference_asset_ids"]


def graph_structure(graph):
    """Allow scalar settings to change, but keep the trusted graph's nodes and links."""
    if not isinstance(graph, dict) or any(not isinstance(node, dict) or not isinstance(node.get("inputs", {}), dict)
                                          for node in graph.values()):
        return None
    return {key: (node.get("class_type"), {field: value if isinstance(value, list) else None
            for field, value in node.get("inputs", {}).items()}) for key, node in graph.items() if isinstance(node, dict)}


def pure_upscale(graph):
    if not isinstance(graph, dict) or not graph:
        return False
    types = {node.get("class_type") for node in graph.values() if isinstance(node, dict)}
    allowed = {"LoadImage", "LoadImageMask", "ImageScale", "ImageScaleBy", "ImageUpscaleWithModel", "UpscaleModelLoader",
               "SaveImage", "SaveImageAdvanced", "PreviewImage", "ImageCrop", "ImageInvert", "ImageBatch", "ImageBlend"}
    return bool(types & {"ImageScale", "ImageScaleBy", "ImageUpscaleWithModel"}) and "LoadImage" in types and types <= allowed
