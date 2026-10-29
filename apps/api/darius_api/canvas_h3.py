"""MiniMax H3 video boards: pinned inputs and immutable shared-queue recipes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from secrets import randbelow
from typing import Literal

import requests
from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select, text

from .canvas_document import StrictModel, PRESETS
from .canvas_moss import digest
from .database import Asset, CanvasGenerationRecord as Generation, CanvasRevisionRecord as Revision

MODES = ("animate-image", "camera-direction", "reference-video")
PROFILES = {"minimax-h3-" + mode + "-v1": mode for mode in MODES}
ANIMATE = "minimax-h3-animate-image-v1"
DURATIONS = tuple(range(5, 16))
RESOLUTIONS = {"native": "Workflow default", "480p": "480p class", "720p": "720p class", "1080p": "1080p class"}
REFERENCE_SCALE = 1.5000000000000002  # Exact imported multiplier, including tie rounding.
PINS = {
 ANIMATE: "09f1bd0e38d99850c85d6ba623b447a8fd23990bbfd92ec03e8b0929a9cfc6e2",
 "minimax-h3-camera-direction-v1": "38a94c35f37a7f52bb2e35643fcf3a267486258e430e5abe295099aa43a19291",
 "minimax-h3-reference-video-v1": "2f6e6025b3fc6f96fcc0ff58f39dc99d41b72cc6574f00da5717e8914158efaa",
}

class MediaBinding(StrictModel):
 id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
 assetId: str = Field(min_length=1, max_length=36)
 assetVersionId: str = Field(pattern=r"^[a-f0-9]{64}$")
 mediaKind: Literal["image"] = "image"
 role: Literal["starting-frame", "camera-source", "subject", "environment", "style"] = "subject"
 token: int = Field(default=1, ge=1, le=9)

class VideoDraft(StrictModel):
 prompt: str = Field(default="", max_length=30000)
 camera: str = Field(default="", max_length=4000)
 audio: str = Field(default="", max_length=4000)
 inputs: list[MediaBinding] = Field(default_factory=list, max_length=9)
 seconds: int = Field(default=10, ge=5, le=15)
 turbo: bool = True
 upscaleDevice: Literal["cuda", "cpu"] = "cuda"
 preset: Literal["square", "poster", "photo", "portrait", "standard", "vertical", "wide", "ultrawide"] = "wide"
 resolution: Literal["native", "480p", "720p", "1080p"] = "native"

 @model_validator(mode="after")
 def unique(self):
  if len({i.id for i in self.inputs}) != len(self.inputs) or len({i.token for i in self.inputs}) != len(self.inputs):
   raise ValueError("Media bindings and Picture labels must be unique")
  return self

class VideoConfig(StrictModel):
 schemaVersion: Literal[1] = 1
 family: Literal["minimax-h3"] = "minimax-h3"
 activeMode: Literal["animate-image", "camera-direction", "reference-video"] = "animate-image"
 modeDrafts: dict[Literal["animate-image", "camera-direction", "reference-video"], VideoDraft] = Field(default_factory=lambda: {m: VideoDraft(seconds=5 if m == "camera-direction" else 10) for m in MODES})

 @model_validator(mode="before")
 @classmethod
 def legacy_camera_timing(cls, value):
  # Old camera drafts stored 10 by default but always rendered 124 frames.
  # Preserve that behavior on read; new drafts carry explicit size fields.
  if isinstance(value,dict):
   camera=value.get("modeDrafts",{}).get("camera-direction")
   if isinstance(camera,dict) and "preset" not in camera and "resolution" not in camera and camera.get("seconds",10)==10:
    value=deepcopy(value);value["modeDrafts"]["camera-direction"]["seconds"]=5
  return value

 @model_validator(mode="after")
 def complete(self):
  for mode in MODES: self.modeDrafts.setdefault(mode, VideoDraft(seconds=5 if mode == "camera-direction" else 10))
  return self


def timing(mode, seconds):
 n = max(5, round(seconds * 24))
 frames = n + (5 - n % 17) % 17
 return {"requestedSeconds": seconds, "frames": frames, "fps": 24, "nominalSeconds": frames / 24}


def output_size(mode, preset="wide"):
 # Installed core ResolutionSelector uses 1024**2 pixels per megapixel, ties-to-even.
 import math
 mp = 1 if mode == "animate-image" else .5
 _, w, h = PRESETS[preset]
 scale = math.sqrt(mp * 1024 * 1024 / (w * h))
 return round(w * scale / 32) * 32, round(h * scale / 32) * 32


def video_dimensions(mode, preset="wide", resolution="native"):
 """Return both generation and final dimensions; reference mode has two stages."""
 import math
 if mode not in MODES or preset not in PRESETS or resolution not in RESOLUTIONS:
  raise ValueError("Choose a supported video mode, aspect ratio and resolution")
 if resolution == "native":
  base_w, base_h = output_size(mode, preset)
  width, height = ((round(base_w * REFERENCE_SCALE / 32) * 32, round(base_h * REFERENCE_SCALE / 32) * 32)
                   if mode == "reference-video" else (base_w, base_h))
 else:
  short = int(resolution.removesuffix("p"))
  _, w, h = PRESETS[preset]
  align = lambda value: max(32, math.ceil(value / 32) * 32)
  width, height = align(short * w / min(w, h)), align(short * h / min(w, h))
  base_w, base_h = ((max(32, round(width / 1.5 / 32) * 32), max(32, round(height / 1.5 / 32) * 32))
                    if mode == "reference-video" else (width, height))
 return {"preset": preset, "resolution": resolution, "width": width, "height": height,
         "generationWidth": base_w, "generationHeight": base_h}


def artifacts(settings, profile):
 if profile not in PROFILES: raise ValueError("Unknown MiniMax H3 profile")
 directory = settings.repository_root / "workflows/canvas" / profile
 graph = json.loads((directory / "template.api.json").read_text(encoding="utf-8"))
 manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
 if digest(graph) != PINS[profile] or manifest["templateDigest"] != PINS[profile] or manifest["profileId"] != profile:
  raise ValueError("MiniMax H3 template changed; register a new version")
 if hashlib.sha256((directory / "source.ui.json").read_bytes()).hexdigest() != manifest["sourceUiDigest"]:
  raise ValueError("MiniMax H3 original workflow changed")
 return graph, manifest


def validate_inputs(session, project_id, config):
 for draft in config.modeDrafts.values():
  for binding in draft.inputs:
   asset = session.get(Asset, binding.assetId)
   if not asset or asset.project_id != project_id or asset.kind != binding.mediaKind or asset.content_hash != binding.assetVersionId:
    raise ValueError("Choose an exact image version from this project")


def compile_graph(settings, config, seed, media, *, content=None):
 mode = config.activeMode; profile = "minimax-h3-" + mode + "-v1"
 draft = config.modeDrafts[mode]; graph, manifest = artifacts(settings, profile)
 if not draft.prompt.strip(): raise ValueError("Describe the scene and action before generating")
 refs = sorted(draft.inputs, key=lambda b: b.token)
 if not refs: raise ValueError("Choose a starting image" if mode != "reference-video" else "Choose at least one reference image")
 if mode != "reference-video" and len(refs) != 1: raise ValueError("This mode uses exactly one source image")
 if mode == "reference-video" and [r.token for r in refs] != list(range(1, len(refs)+1)):
  raise ValueError("Picture labels have a gap. Explicitly remap references and update the prompt before generating")
 prompt = draft.prompt
 if mode == "camera-direction" and draft.camera.strip(): prompt += "\n\nCamera direction:\n" + draft.camera.strip()
 if draft.audio.strip(): prompt += "\n\nAudio direction:\n" + draft.audio.strip()
 for kind, number in re.findall(r"<(Picture|Video|Audio)\s+(\d+)>", prompt, re.I):
  if kind.lower() != "picture" or not 1 <= int(number) <= len(refs):
   raise ValueError("The prompt references unavailable media: " + kind + " " + number)
 size=video_dimensions(mode,draft.preset,draft.resolution)
 width,height=size["width"],size["height"]; clock=timing(mode,draft.seconds)
 if mode == "animate-image":
  graph["reference"]["inputs"]["image"] = media[refs[0].id]
  graph["14"]["inputs"]["value"] = prompt
  graph["20"]["inputs"]["value"] = draft.seconds
  graph["15"]["inputs"]["aspect_ratio"] = PRESETS[draft.preset][0]
  if draft.resolution != "native":
   graph["16"]["inputs"].update(width=width,height=height)
  noise,sink="37","4"
 elif mode == "camera-direction":
  graph["114"]["inputs"]["image"] = media[refs[0].id]
  graph["193"]["inputs"]["value"] = prompt
  graph["105:126"]["inputs"]["value"] = draft.turbo
  graph["105:125"]["inputs"]["value"] = 8
  graph["157"]["inputs"]["aspect_ratio"] = PRESETS[draft.preset][0]
  graph["105:104"]["inputs"]["length"] = clock["frames"]
  if draft.resolution != "native":
   graph["105:104"]["inputs"].update(width=width,height=height)
   graph["119"]["inputs"]["megapixels"] = width*height/(1024*1024)
  noise,sink="105:15","92"
 else:
  graph["140"]["inputs"]["device"] = draft.upscaleDevice
  for k in ["51","49","50"]: graph.pop(k,None)
  graph["265"]["inputs"] = {k:v for k,v in graph["265"]["inputs"].items() if not k.startswith("ref_images.")}
  for index,b in enumerate(refs):
   node="darius_ref_"+str(index);graph[node]={"class_type":"LoadImage","inputs":{"image":media[b.id]}}
   graph["265"]["inputs"]["ref_images.ref_image_"+str(index)]=[node,0]
  graph["263"]["inputs"]["value"]=prompt
  graph["259"]["inputs"]["value"]=draft.seconds
  graph["252"]["inputs"]["aspect_ratio"]=PRESETS[draft.preset][0]
  if draft.resolution != "native":
   graph["265"]["inputs"].update(width=size["generationWidth"],height=size["generationHeight"])
   graph["140"]["inputs"].pop("mode.scale",None)
   graph["140"]["inputs"].update(mode="target dimensions", **{"mode.width":width,"mode.height":height})
  noise,sink="256","214"
 graph[noise]["inputs"]["noise_seed"]=seed
 return graph,{**manifest,"adapterVersion":profile,"profileId":profile,"profileName":{"animate-image":"Image animation · 4-step","camera-direction":"Camera · " + ("Turbo 8-step" if draft.turbo else "Base 20-step"),"reference-video":"Reference · two-stage"}[mode],
  "mode":mode,"videoConfig":config.model_dump(),"conditioningPrompt":prompt,"promptCompiler":"h3-written-direction-v2","seed":str(seed),"width":width,"height":height,"videoDimensions":size,"timing":clock,"sampler":noise,"outputNode":sink,
  "preparedGraphDigest":digest(graph),"mediaTokenMap":[{**r.model_dump(),"label":"Picture "+str(i+1),"workerInput":media[r.id]} for i,r in enumerate(refs)],
  "inputFit":"Starting frame stretched to output; camera source scaled to output pixel budget" if mode != "reference-video" else "Aspect preserved; max reference size, downscale only",
  "stages":[{"sink":k,"role":v} for k,v in manifest["outputs"].items()],
  "executionSettings": {k: deepcopy(n) for k,n in graph.items() if n["class_type"] not in {"PrimitiveStringMultiline", "LoadImage", "Text"}},
  "availableModelFingerprints": model_fingerprints(settings, graph)}


def model_fingerprints(settings, graph):
 root=settings.block_party_comfy_root or (settings.comfyui_output_dir.parent if settings.comfyui_output_dir else None)
 if root is None:return {"available":False}
 result={}
 for node in graph.values():
  for key,folder in (("unet_name","diffusion_models"),("clip_name","text_encoders"),("vae_name","vae"),("lora_name","loras"),("lora_01","loras"),("model_name","latent_upscale_models")):
   name=node["inputs"].get(key)
   if not isinstance(name,str) or name=='None':continue
   path=root/'models'/folder/name
   try:
    stat=path.stat()
    with path.open('rb') as f:header=hashlib.sha256(f.read(65536)).hexdigest()
    result[name]={"bytes":stat.st_size,"mtimeNs":str(stat.st_mtime_ns),"first64KiBSha256":header,"scheme":"size+mtime+header; not a full model checksum"}
   except OSError:result[name]={"available":False}
 return result


def readiness(settings, profile, graph=None):
 from .providers import ComfyMcpProvider
 graph = graph or artifacts(settings,profile)[0]
 try:
  schemas=ComfyMcpProvider(settings).live_node_schemas(graph)
  issues=[]
  for node in graph.values():
   spec=schemas[node["class_type"]].get("input",{}).get("required",{})
   for field in ["unet_name","clip_name","vae_name","lora_name","model_name","lora_01"]:
    if field not in node["inputs"] or field not in spec:continue
    s=spec[field];choices=s[0] if isinstance(s[0],list) else s[1].get("options",[]) if len(s)>1 else []
    if choices and node["inputs"][field] not in choices:issues.append("Missing model: "+str(node["inputs"][field]))
  return {"ready":not issues,"issues":issues}
 except Exception as exc:return {"ready":False,"issues":[str(exc)]}


def upload_inputs(settings, session, project_id, config):
 validate_inputs(session,project_id,config)
 return upload_bindings(settings,session,project_id,config.modeDrafts[config.activeMode].inputs)


def upload_bindings(settings, session, project_id, bindings):
 from .media import _hash
 media={}; receipts=[]
 http=requests.Session();http.trust_env=False
 from urllib.parse import urlparse
 url=urlparse(settings.comfyui_base_url)
 if url.scheme!='http' or url.hostname not in {'127.0.0.1','localhost','::1'}:raise ValueError('ComfyUI inputs require a loopback server')
 for binding in bindings:
  asset=session.get(Asset,binding.assetId)
  if not asset or asset.project_id!=project_id or asset.kind!="image" or asset.content_hash!=binding.assetVersionId:raise ValueError("Choose an exact image version from this project")
  asset=session.get(Asset,binding.assetId);path=Path(asset.path)
  if not path.is_file() or path.stat().st_size>64*1024*1024 or _hash(path)!=binding.assetVersionId:raise ValueError('Pinned image is missing or changed; choose its current version explicitly')
  filename=binding.assetVersionId+path.suffix.lower()
  with path.open('rb') as handle:
   response=http.post(settings.comfyui_base_url+'/upload/image',files={'image':(filename,handle,asset.mime_type)},data={'subfolder':'darius/pinned','overwrite':'false'},timeout=60)
  response.raise_for_status();data=response.json();name=data['name'];folder=data.get('subfolder','')
  if Path(name).name!=name or '..' in folder.replace('\\','/').split('/'):raise ValueError('Unsafe input receipt')
  media[binding.id]=(folder+'/'+name).lstrip('/')
  receipts.append({**binding.model_dump(),'workerInput':media[binding.id],'sourceHash':asset.content_hash})
 return media,receipts


def generate(settings, session_factory, registry, project_id, document_id, payload):
 from .canvas_recipe_jobs import generate as queue_recipe
 import sys
 return queue_recipe(settings, session_factory, registry, project_id, document_id, payload, sys.modules[__name__])


def retain_intermediate(session, settings, job, error):
 """Stage-2 failure never promotes an intermediate into the final result."""
 from .providers import PartialVideoError
 from .media import ingest_generated
 from .services import new_id, add_event
 if not isinstance(error, PartialVideoError) or not job.input_payload.get('canvas_generation_id'): return
 generation=session.get(Generation,job.input_payload['canvas_generation_id'])
 if not generation or generation.project_id!=job.project_id or generation.provenance_json.get('profileId')!='minimax-h3-reference-video-v1':return
 ids=[]
 for path in error.outputs:
  media=ingest_generated(path,settings,job.project_id)
  if media.kind!='video' or not media.duration:continue
  asset=Asset(id=new_id(),project_id=job.project_id,kind='video',role='generation',path=str(media.path),content_hash=media.content_hash,mime_type=media.mime_type,width=media.width,height=media.height,duration=media.duration,fps=media.fps,sample_rate=media.sample_rate,parent_asset_ids=[i['assetId'] for i in generation.provenance_json['mediaReceipts']],provider=job.provider,workflow_run_id=job.id,metadata_json={**media.metadata,'display_name':'Video stage 1 · intermediate','h3_output_role':'intermediate','h3_final_failed':True})
  session.add(asset);ids.append(asset.id)
  add_event(session,job.project_id,'asset.created','asset',asset.id,{'job_id':job.id,'role':'intermediate'})
 job.output_asset_ids=ids;job.external_job_id=error.prompt_id
 generation.provenance_json={**generation.provenance_json,'partial':True,'intermediateAssetIds':ids,'comfyPromptId':error.prompt_id,'recovery':failure_recovery(str(error), bool(ids))}


def verify_outputs(session, job, provenance):
 expected=list(provenance['outputs'])
 if len(job.output_asset_ids)!=len(expected):raise ValueError('H3 did not return every declared video stage')
 for index,key in enumerate(job.output_asset_ids):
  asset=session.get(Asset,key)
  streams=asset.metadata_json.get('ffprobe',{}).get('streams',[])
  if asset.kind!='video' or not asset.duration or not any(s.get('codec_type')=='audio' for s in streams):
   raise ValueError('H3 output lacks a valid video or audio stream; final result was not accepted')
  role=provenance['outputs'][expected[index]]
  asset.metadata_json={**asset.metadata_json,'h3_output_role':role,'h3_mode':provenance['mode'],'h3_output_sink':expected[index]}


# Shared recipe-job adapter interface. Historical profile graphs are unchanged.
Config = VideoConfig
CONFIG_FIELD = "video"
OUTPUT_KIND = "video"
def active_inputs(config): return config.modeDrafts[config.activeMode].inputs
def active_profile_name(config): return config.activeMode


def failure_recovery(detail, preview_saved):
 oom = any(word in detail.lower() for word in ('out of memory', 'allocation on device', 'cuda out of memory'))
 upscale = 'MinimaxH3LatentUpscaler3D' in detail or 'upscal' in detail.lower()
 return {"stage": "upscale" if upscale else "final-stage", "outOfMemory": oom,
  "message": ("Preview saved; final upscale ran out of GPU memory." if oom and upscale else "Preview saved; the final video stage failed.") if preview_saved else "The final video stage failed; no preview was recovered.",
  "canResumeFinalOnly": False,
  "explanation": "No durable latent checkpoint is saved. Generate reruns the original workflow; ComfyUI may reuse its cache, but an upscale-only resume is not guaranteed."}
