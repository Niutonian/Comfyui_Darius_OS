"""Versioned boards for the remaining default image-generation/edit recipes."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator
from .canvas_document import StrictModel, PRESETS
from .canvas_moss import digest
from . import canvas_h3 as h3

FLUX = "flux3-klein-t2i-v1"
KREA = "krea2-turbo-t2i-v1"
QWEN = "qwen21-t2i-v1"
EDIT = "qwen21-edit-v1"
Profile = Literal["flux3-klein-t2i-v1", "krea2-turbo-t2i-v1", "qwen21-t2i-v1", "qwen21-edit-v1"]
PROFILES = {FLUX: "FLUX 3 Klein", KREA: "Krea 2 Turbo", QWEN: "Qwen Image 2.1", EDIT: "Qwen Image 2.1 · Edit"}
CONFIG_FIELD = "image"
OUTPUT_KIND = "image"
PINS = {'flux3-klein-t2i-v1': {'templateDigest': '4c6624ae8957aa2ad002a0ecc639fb7bd17106be6969c53ce584df99ac810c36', 'manifestDigest': '96b24bf459b939c62cc7c9a2a6fd3dfdcc2e815dd1faab022e00fdb74685b8ae'}, 'krea2-turbo-t2i-v1': {'templateDigest': 'c4eb24e805f77db83234a1254ae40521290dede23d23f55ea72d68fc3eb9d39e', 'manifestDigest': 'f8aa50244eeb2a63f645cd95e633bc797d60d631e389538a81745a620813dbae'}, 'qwen21-t2i-v1': {'templateDigest': 'd775ee0850ee88eb5477026f4ef9d73fd5c302f31555bbf3a9eea405df167f04', 'manifestDigest': 'ad38e481a37341277ce31c2d2eb6f98785d039d3ec9e44d2ea55bbd88b7d5465'}, 'qwen21-edit-v1': {'templateDigest': 'ec1e03964de55c23f96ac54eccf0995af109bd4d7fb48b60c4e481ba4d991840', 'manifestDigest': '8450f29febd2816c973d29c938972a74ce547cc41ea0bd0c872791cfd4d5d338'}}


class ImageInput(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    assetId: str = Field(min_length=1, max_length=36)
    assetVersionId: str = Field(pattern=r"^[a-f0-9]{64}$")
    mediaKind: Literal["image"] = "image"
    token: int = Field(default=1, ge=1, le=10)


class ImageDraft(StrictModel):
    prompt: str = Field(default="", max_length=30000)
    negativePrompt: str = Field(default="", max_length=6000)
    inputs: list[ImageInput] = Field(default_factory=list, max_length=10)
    preset: Literal["square", "poster", "photo", "portrait", "standard", "vertical", "wide", "ultrawide"] = "square"
    megapixels: Literal[1, 4] = 1
    steps: int = Field(default=25, ge=1, le=150, strict=True)
    cfg: float = Field(default=1, ge=0, le=20)
    seed: str | None = None
    enhance: bool = False
    styleEnabled: bool = False
    styleLora: str = Field(default="krea2_darkbrush.safetensors", pattern=r"^krea2_[a-zA-Z0-9_-]+\.safetensors$", max_length=120)
    styleStrength: float = Field(default=.8, ge=-2, le=2)
    styleText: str = Field(default="muted minimalist sketch style", max_length=2000)
    followSource: bool = True
    referenceResolution: Literal[0, 1024, 2048] = 0

    @field_validator("seed", mode="before")
    @classmethod
    def strict_seed(cls, value):
        from .canvas_fibo import seed_value
        return None if value is None else str(seed_value(value))

    @model_validator(mode="after")
    def unique_bindings(self):
        if len({i.id for i in self.inputs}) != len(self.inputs) or len({i.token for i in self.inputs}) != len(self.inputs):
            raise ValueError("Image bindings and prompt labels must be unique")
        return self


def defaults(profile):
    return ImageDraft(steps=50 if profile == FLUX else 8 if profile == KREA else 25,
        cfg=3.5 if profile == FLUX else 1, preset="poster" if profile == FLUX else "square",
        negativePrompt="out of frame head" if profile == FLUX else "", enhance=profile in {FLUX, KREA})


class Config(StrictModel):
    schemaVersion: Literal[1] = 1
    activeProfile: Profile = FLUX
    drafts: dict[Profile, ImageDraft] = Field(default_factory=dict)

    @model_validator(mode="after")
    def complete(self):
        for profile in PROFILES:
            self.drafts.setdefault(profile, defaults(profile))
        return self


def active_inputs(config): return config.drafts[config.activeProfile].inputs

def active_profile_name(config): return config.activeProfile


def artifacts(settings, profile):
    if profile not in PROFILES:
        raise ValueError("Unknown image recipe")
    root = settings.repository_root / "workflows/canvas" / profile
    graph = json.loads((root / "template.api.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if digest(graph) != PINS[profile]["templateDigest"] or digest(manifest) != PINS[profile]["manifestDigest"]:
        raise ValueError("Image recipe artifacts changed; register a new version")
    if hashlib.sha256((root / "source.ui.json").read_bytes()).hexdigest() != manifest["sourceUiDigest"]:
        raise ValueError("The original image workflow changed")
    return graph, manifest


def validate_inputs(session, project_id, config):
    from .database import Asset
    for draft in config.drafts.values():
        for binding in draft.inputs:
            asset = session.get(Asset, binding.assetId)
            if not asset or asset.project_id != project_id or asset.kind != "image" or asset.content_hash != binding.assetVersionId:
                raise ValueError("Choose an exact image version from this project")


def upload_inputs(settings, session, project_id, config):
    validate_inputs(session, project_id, config)
    media, receipts = h3.upload_bindings(settings, session, project_id, active_inputs(config))
    from .database import Asset
    for receipt in receipts:
        asset = session.get(Asset, receipt["assetId"])
        receipt.update(width=asset.width, height=asset.height)
    return media, receipts


def output_size(profile, draft, source=None):
    if profile == EDIT and draft.followSource:
        if not source or not source.get("width") or not source.get("height"):
            return None
        width, height = source["width"], source["height"]
        if draft.referenceResolution:
            ratio = width / height
            width = math.sqrt(draft.referenceResolution ** 2 * ratio)
            height = math.sqrt(draft.referenceResolution ** 2 / ratio)
        return max(32, round(width / 32) * 32), max(32, round(height / 32) * 32)
    _, w, h = PRESETS[draft.preset]
    multiple = 16 if profile == FLUX else 32
    scale = math.sqrt(draft.megapixels * 1024 ** 2 / (w * h))
    return round(w * scale / multiple) * multiple, round(h * scale / multiple) * multiple


def _specialize(graph, sink):
    """Resolve known boolean switches, then omit branches that cannot execute."""
    aliases = {}
    for key, node in graph.items():
        if node["class_type"] != "ComfySwitchNode":
            continue
        flag = node["inputs"]["switch"]
        if isinstance(flag, list) and graph[flag[0]]["class_type"] == "PrimitiveBoolean":
            flag = graph[flag[0]]["inputs"]["value"]
        if type(flag) is bool:
            aliases[key] = node["inputs"]["on_true" if flag else "on_false"]
    def resolve(value):
        seen = set()
        while isinstance(value, list) and len(value) == 2 and str(value[0]) in aliases:
            if value[0] in seen: raise ValueError("Cyclic workflow switch")
            seen.add(value[0]); value = aliases[value[0]]
        return value
    for node in graph.values():
        node["inputs"] = {k: resolve(v) for k, v in node["inputs"].items()}
    keep = set()
    def visit(key):
        if key in keep: return
        keep.add(key)
        for value in graph[key]["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in graph:
                visit(value[0])
    visit(sink)
    return {k: v for k, v in graph.items() if k in keep}


def compile_graph(settings, config, seed, media, *, content=None):
    from .canvas_fibo import seed_value
    seed = seed_value(seed)
    profile = config.activeProfile
    draft = config.drafts[profile]
    graph, manifest = artifacts(settings, profile)
    if not draft.prompt.strip(): raise ValueError("Describe the image or edit before generating")
    if content and content.get("regions"):
        raise ValueError("This recipe does not accept drawn regions. Keep region compositions on MOSS/FIBO boards")
    if profile != EDIT and draft.inputs: raise ValueError("Only the Qwen Edit recipe accepts image inputs")
    if profile == EDIT and not draft.inputs: raise ValueError("Choose a source image for Qwen Edit")
    if profile not in {QWEN, EDIT} and draft.megapixels != 1: raise ValueError("This imported recipe uses 1 MP")
    if profile not in {FLUX, KREA} and draft.enhance: raise ValueError("This Qwen recipe has no prompt enhancer")
    if profile != KREA and draft.styleEnabled: raise ValueError("The style LoRA is available only in Krea 2")
    sampler, sink = manifest["sampler"], manifest["outputNode"]
    graph[sampler]["inputs"].update(seed=seed, steps=draft.steps, cfg=draft.cfg)
    selector = graph[manifest["selector"]]["inputs"]
    selector.update(aspect_ratio=PRESETS[draft.preset][0], megapixels=draft.megapixels, multiple=16 if profile == FLUX else 32)
    if profile == FLUX:
        graph["18:17"]["inputs"]["value"] = draft.prompt
        graph["18:5"]["inputs"]["text"] = draft.negativePrompt
        graph["18:16"]["inputs"]["switch"] = draft.enhance
        graph["18:11"]["inputs"]["sampling_mode.seed"] = seed
        encoder, field = "18:4", "text"
    elif profile == KREA:
        if draft.negativePrompt: raise ValueError("Krea Turbo uses zeroed negative conditioning; a negative prompt is not supported")
        graph["30:19"]["inputs"]["value"] = draft.prompt
        graph["30:24"]["inputs"]["value"] = draft.enhance
        graph["30:23"]["inputs"]["value"] = draft.styleEnabled
        graph["30:15"]["inputs"].update(lora_name=draft.styleLora, strength_model=draft.styleStrength)
        graph["30:27"]["inputs"]["string_b"] = draft.styleText
        encoder, field = "30:6", "text"
    else:
        encoder, field = ("459:474" if profile == EDIT else "459:452"), "prompt"
        graph[encoder]["inputs"].update(prompt=draft.prompt, negative_prompt=draft.negativePrompt)
        if profile == EDIT:
            refs = sorted(draft.inputs, key=lambda b: b.token)
            if [r.token for r in refs] != list(range(1, len(refs)+1)):
                raise ValueError("Image labels have a gap. Explicitly update the prompt before remapping references")
            for token in re.findall(r"<image\s*(\d+)>", draft.prompt, re.I):
                if not 1 <= int(token) <= len(refs): raise ValueError("The edit prompt references an unavailable image")
            graph.pop("470", None); graph.pop("475", None)
            graph[encoder]["inputs"] = {k:v for k,v in graph[encoder]["inputs"].items() if not k.startswith("images.")}
            graph[encoder]["inputs"]["resolution"] = draft.referenceResolution
            for binding in refs:
                key = "darius_input_" + str(binding.token)
                graph[key] = {"class_type":"LoadImage", "inputs":{"image":media[binding.id]}}
                graph[encoder]["inputs"]["images.image_"+str(binding.token)] = [key, 0]
            graph["459:468"]["inputs"]["switch"] = not draft.followSource
    # Receipt is on the exact string path consumed by the encoder, including enhancement/style.
    source = graph[encoder]["inputs"][field]
    graph["darius_conditioning"] = {"class_type":"PreviewAny", "inputs":{"source":source}}
    graph[encoder]["inputs"][field] = ["darius_conditioning", 0]
    graph = _specialize(graph, sink)
    size = output_size(profile, draft)
    provenance = {**manifest, "adapterVersion":profile, "profileId":profile, "profileName":PROFILES[profile],
        "imageConfig":config.model_dump(), "conditioningPrompt":draft.prompt, "negativePrompt":draft.negativePrompt,
        "conditioningReceiptNode":"darius_conditioning", "promptEnhancement":draft.enhance, "seed":str(seed),
        "seedSlot":sampler+".seed", "capability":"image-to-image" if profile == EDIT else "text-to-image",
        "width":size[0] if size else None, "height":size[1] if size else None,
        "followSource":profile == EDIT and draft.followSource, "steps":draft.steps, "cfg":draft.cfg,
        "mediaTokenMap":[{**b.model_dump(),"label":"<image"+str(b.token)+">","workerInput":media[b.id]} for b in sorted(draft.inputs,key=lambda b:b.token)],
        "resolutionPolicy":"runtime-selector; 16px FLUX, 32px Krea/Qwen grid; square defaults unchanged",
        "preparedGraphDigest":digest(graph), "availableModelFingerprints":h3.model_fingerprints(settings,graph),
        "executionSettings":{k:deepcopy(n) for k,n in graph.items() if n["class_type"] not in {"PrimitiveStringMultiline","LoadImage"}}}
    return graph, provenance


def readiness(settings, profile, graph=None):
    if graph is None:
        config = Config(activeProfile=profile)
        draft = config.drafts[profile]; draft.prompt = "Dependency inspection"
        if profile == EDIT:
            draft.inputs = [ImageInput(id="source",assetId="inspection",assetVersionId="a"*64)]
        graph, _ = compile_graph(settings,config,42,{"source":"inspection.png"})
    return h3.readiness(settings, profile, graph)


def generate(settings, session_factory, registry, project_id, document_id, payload):
    from .canvas_recipe_jobs import generate as queue_recipe
    import sys
    return queue_recipe(settings,session_factory,registry,project_id,document_id,payload,sys.modules[__name__])


def completed(session, job, generation, metadata):
    from .database import Asset
    p = generation.provenance_json
    actual = metadata.get("canvas_conditioning_prompt")
    if not isinstance(actual, str) or not actual.strip():
        raise ValueError("Image result has no effective prompt receipt")
    config = Config.model_validate(p["imageConfig"])
    draft = config.drafts[config.activeProfile]
    if not draft.enhance:
        expected = draft.prompt + (", " + draft.styleText if config.activeProfile == KREA and draft.styleEnabled else "")
        if actual != expected:
            raise ValueError("Image conditioning receipt differs from the authorized prompt")
    if len(job.output_asset_ids) != 1:
        raise ValueError("The image recipe must produce exactly one final image")
    asset = session.get(Asset, job.output_asset_ids[0])
    if asset.kind != "image" or not asset.width or not asset.height:
        raise ValueError("The image recipe did not return a valid image")
    if p.get("width") and (asset.width, asset.height) != (p["width"], p["height"]):
        raise ValueError("The rendered image dimensions differ from the saved recipe")
    generation.provenance_json = {**p, "conditioningPromptVerified":True, "effectiveConditioningPrompt":actual,
        "effectivePromptHash":hashlib.sha256(actual.encode()).hexdigest(), "actualWidth":asset.width, "actualHeight":asset.height}
