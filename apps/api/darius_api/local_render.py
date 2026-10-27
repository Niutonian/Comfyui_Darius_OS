"""Standing permission for verified local graphs, scoped to one project and job."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select, text

from .database import (ActionPlan, ActionPlanTransition, Asset, Conversation, GenerationRecord,
                       Job, LocalRenderPermission, Message)
from .providers import ProviderError
from .workflows import WorkflowContract


# Deliberately enumerated local nodes. Unknown/custom/API nodes require review.
LOCAL_NODES = {name: "nodes" for name in (
    "CheckpointLoaderSimple", "CLIPTextEncode", "CLIPSetLastLayer", "VAELoader", "LoraLoader",
    "LoraLoaderModelOnly", "KSampler", "KSamplerAdvanced", "EmptyLatentImage", "VAEEncode",
    "VAEDecode", "VAEEncodeTiled", "VAEDecodeTiled", "SaveImage", "PreviewImage", "LoadImage",
    "LoadImageMask", "ImageScale", "ImageScaleBy", "ImageInvert", "ImageBatch", "ImagePadForOutpaint",
    "ConditioningCombine", "ConditioningConcat", "ConditioningAverage", "ConditioningSetArea",
    "ConditioningSetMask", "ConditioningZeroOut", "ConditioningSetTimestepRange",
    "ControlNetLoader", "ControlNetApplyAdvanced", "UNETLoader", "CLIPLoader", "DualCLIPLoader",
)}
LOCAL_NODES.update({
    "MiniMaxH3ReferenceToVideo": "comfy_extras.nodes_minimax_h3",
    "MiniMaxH3ImageToVideo": "comfy_extras.nodes_minimax_h3",
    "SaveVideo": "comfy_extras.nodes_video",
    "CreateVideo": "comfy_extras.nodes_video",
    "VAEDecodeAudio": "comfy_extras.nodes_audio",
    "ResolutionSelector": "comfy_extras.nodes_resolution",
    "ComfyMathExpression": "comfy_extras.nodes_math",
    "ComfySwitchNode": "comfy_extras.nodes_logic",
    "PrimitiveFloat": "comfy_extras.nodes_primitive",
    "PrimitiveInt": "comfy_extras.nodes_primitive",
    "PrimitiveBoolean": "comfy_extras.nodes_primitive",
    "PrimitiveStringMultiline": "comfy_extras.nodes_primitive",
    "EmptyImage": "nodes",
    "FluxGuidance": "comfy_extras.nodes_flux",
    "EmptySD3LatentImage": "comfy_extras.nodes_sd3",
    "ModelSamplingFlux": "comfy_extras.nodes_model_advanced",
    "ModelSamplingSD3": "comfy_extras.nodes_model_advanced",
    "RandomNoise": "comfy_extras.nodes_custom_sampler",
    "BasicGuider": "comfy_extras.nodes_custom_sampler",
    "CFGGuider": "comfy_extras.nodes_custom_sampler",
    "KSamplerSelect": "comfy_extras.nodes_custom_sampler",
    "BasicScheduler": "comfy_extras.nodes_custom_sampler",
    "SamplerCustomAdvanced": "comfy_extras.nodes_custom_sampler",
    "TextEncodeQwenImage21": "comfy_extras.nodes_qwen",
    "QwenImage21Cache": "comfy_extras.nodes_qwen",
    "SaveImageAdvanced": "comfy_extras.nodes_images",
    # Reviewed built-in FLUX helpers: local tensors/text only, not API nodes.
    "EmptyFlux2LatentImage": "comfy_extras.nodes_flux",
    "Flux3LayoutPrompt": "comfy_extras.nodes_flux",
    "CreateBoundingBoxes": "comfy_extras.nodes_bounding_boxes",
    "PreviewAny": "comfy_extras.nodes_preview_any",
    "TextGenerate": "comfy_extras.nodes_textgen",
    # Audited video helpers: local model patches and image resampling only.
    "MiniMaxH3SigmaShift": "comfy_extras.nodes_minimax_h3",
    "ModelAttentionBackend": "comfy_extras.nodes_model_advanced",
    "ImageScaleToTotalPixels": "comfy_extras.nodes_post_processing",
    # Exact node identities, not blanket trust of either custom-node pack.
    # Camera compiles trajectory text/options; ShowText updates UI metadata;
    # KJ attaches a local preview wrapper (its tiny VAE is loaded locally).
    "H3LocalCameraEditor": "custom_nodes.3d-Camera-control-H3-Minimax",
    "ShowText|pysssss": "custom_nodes.comfyui-custom-scripts",
    "ModelPreviewOverrideKJ": "custom_nodes.comfyui-kjnodes",
})
# These installed H3 nodes load local weights and operate on supplied tensors.
# Do not trust the whole extension: it also includes remote-encoding nodes.
LOCAL_NODES.update({name: "custom_nodes.ComfyUI-H3-Multishot" for name in (
    "H3ModelLoaderAny", "H3ClipLoaderAny", "H3Keyframes", "H3ConditionStrength", "H3LoraStack",
)})


def requests_render(text):
    """Conservative fallback for explicit media execution, never draft-only work."""
    from .media_intent import execution_requested
    return execution_requested(text)


def permission_enabled(session, project_id):
    permission = session.get(LocalRenderPermission, project_id)
    return bool(permission and permission.enabled)


def inspect_local_nodes(settings, names=None):
    endpoint = urlparse(settings.comfyui_base_url)
    if endpoint.scheme != "http" or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"} or endpoint.username or endpoint.password:
        raise ProviderError("Automatic rendering requires a loopback ComfyUI server")
    try:
        # Do not follow a redirect from the loopback server to an external service.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        def inspect(name):
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(settings.comfyui_base_url + "/object_info/" + name, timeout=3) as response:
                return json.load(response)
        # Query only required built-ins; the full registry can run expensive custom-node discovery.
        result = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for info in pool.map(inspect, names if names is not None else LOCAL_NODES):
                if not isinstance(info, dict):
                    raise ValueError("Invalid node metadata")
                result.update(info)
        return result
    except (OSError, ValueError) as exc:
        raise ProviderError("Could not verify installed ComfyUI nodes; use Review generation") from exc


def verify_local_graph(settings, contract, graph):
    if contract.execution_provider != "local-comfyui" or not contract.runtime_mapping.api_format or not contract.enabled:
        raise ProviderError("Prepare an API graph before automatic local rendering")
    if contract.estimated_cost not in (None, 0):
        raise ProviderError("Workflows with an external cost require manual approval")
    if not isinstance(graph, dict) or not graph or len(graph) > 500:
        raise ProviderError("Invalid local graph")
    source_asset_ids = getattr(contract, "source_asset_ids", [])
    allowed_image_prefixes = tuple(f"darius-{asset_id}" for asset_id in source_asset_ids)
    for node in graph.values():
        if not isinstance(node, dict) or node.get("class_type") not in {"LoadImage", "LoadImageMask"}:
            continue
        image = node.get("inputs", {}).get("image") if isinstance(node.get("inputs"), dict) else None
        filename = Path(image.replace("\\", "/")).name if isinstance(image, str) else ""
        if not filename or not allowed_image_prefixes or not filename.startswith(allowed_image_prefixes):
            raise ProviderError(
                "This workflow contains an image without active-project provenance. Prepare a new draft and bind the project asset."
            )
    for node in graph.values():
        if not isinstance(node, dict) or node.get("class_type") not in LOCAL_NODES or not isinstance(node.get("inputs"), dict):
            raise ProviderError("This graph contains unverified or external nodes. Use Review generation for manual approval.")
    installed = inspect_local_nodes(settings, {node["class_type"] for node in graph.values()})
    if not isinstance(installed, dict):
        raise ProviderError("ComfyUI node information is unavailable")
    for node in graph.values():
        name = node["class_type"]
        info = installed.get(name, {})
        if not isinstance(info, dict) or info.get("python_module") != LOCAL_NODES[name] or info.get("api_node"):
            raise ProviderError(f"{name} is not a verified local node. Use Review generation.")


def launch_local_job(settings, job_id):
    """Wake the shared Canvas dispatcher or target one explicitly requested legacy job."""
    env = {**os.environ, "DARIUS_DATA_DIR": str(settings.data_dir), "DARIUS_DATABASE_URL": settings.database_url,
           "DARIUS_WORKFLOW_DEFINITIONS_DIR": str(settings.workflow_definitions_dir)}
    log_path = settings.data_dir / "jobs" / job_id / "worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Canvas boards share one durable dispatcher, not one renderer per board.
    from .database import make_engine, make_session_factory
    engine = make_engine(settings.database_url)
    try:
        with make_session_factory(engine).begin() as session:
            job = session.get(Job, job_id)
            if job and job.status == "queued" and not job.input_payload.get("worker_ready"):
                job.input_payload = {**job.input_payload, "worker_ready": True}
            args = ["--canvas-queue"] if job and job.input_payload.get("canvas_generation_id") else ["--job-id", job_id]
    finally:
        engine.dispose()
    with log_path.open("ab") as log:
        subprocess.Popen([sys.executable, "-m", "darius_api.worker", *args],
                         cwd=settings.repository_root, env=env, stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def message_render_request(session, source):
    from .media_intent import resolve_request
    if isinstance(source.metadata_json.get("local_render_request"), str):
        return source.metadata_json["local_render_request"]
    messages = session.scalars(select(Message).where(Message.conversation_id == source.conversation_id,
        Message.created_at <= source.created_at).order_by(Message.created_at.desc(), Message.id.desc()).limit(40)).all()
    from .assistant_context import scoped_asset_ids, project_memory
    conversation = session.get(Conversation, source.conversation_id)
    attached = scoped_asset_ids(session, conversation.project_id, source.metadata_json.get("asset_ids", [])) if conversation else []
    if not attached and conversation:
        attached = project_memory(session, conversation.project_id)["reference_asset_ids"]
    return resolve_request(source.content, {"attached_asset_ids": attached, "messages": [
        {**(item.metadata_json or {}), "role": item.role, "content": item.content}
        for item in reversed(messages)]})


def queue_local_render(settings, registry, session_factory, project_id, message_id, workflow_id):
    """Legacy chat submissions are closed; existing jobs keep their worker path."""
    from .creative_chat import require_text_capability
    with session_factory() as capability_session:
        require_text_capability(capability_session, project_id, message_id)
    from .media_intent import requested_count, output_kind, is_media_request
    with session_factory() as session:
        source = session.get(Message, message_id)
        conversation = session.get(Conversation, source.conversation_id) if source else None
        if not source or source.role != "user" or not conversation or conversation.project_id != project_id:
            raise ProviderError("A current project user message is required to queue a render")
        request = message_render_request(session, source)
        if not requests_render(request):
            raise ProviderError("This message does not authorize starting a render. Prepare a draft for review instead.")
        count = requested_count(request)
        if not 1 <= count <= 6:
            raise ProviderError("Render batches support 1–6 separate takes. Split this request into smaller batches.")
        contract = registry.get(workflow_id)
        if contract.project_id and contract.project_id != project_id:
            raise ProviderError("Workflow does not belong to this project")
        visual_plan = source.metadata_json.get("visual_plan") or {}
        shots = visual_plan.get("shots") or []
        distinct_shots = len(shots) > 1
        indices = list(range(count))
        if distinct_shots:
            if len(shots) != count or visual_plan.get("request") != request:
                raise ProviderError("The saved shot plan no longer matches this request; prepare a fresh plan before rendering.")
            if contract.generation_task_id != message_id:
                raise ProviderError("Prepare a shot workflow for this message before rendering.")
            indices = [i for i, shot in enumerate(shots) if shot["id"] == contract.generation_brief_id]
            if len(indices) != 1:
                raise ProviderError("The prepared workflow needs a valid brief_id from this message's visual plan.")
        if is_media_request(request) and contract.output.kind != output_kind(request):
            raise ProviderError("The prepared workflow has the wrong output type for this request. Nothing was queued.")
        if not distinct_shots and count > 1 and re.search(r"\b(?:first|second|third|respectively)\b|(?:^|\n)\s*[1-6][.)]", request, re.I):
            raise ProviderError("This batch describes separate shot briefs. Generate each shot separately so its subject is preserved; nothing was queued.")
    # Freeze the resolved intent before any job exists, so a retry of 'proceed'
    # cannot shrink a partially queued batch to one take.
    with session_factory.begin() as session:
        source = session.get(Message, message_id)
        source.metadata_json = {**source.metadata_json, "local_render_request": request, "local_render_batch_count": count}
    results = []
    for index in indices:
        results.append(_queue_local_take(settings, registry, session_factory, project_id, message_id, workflow_id, index, count))
    return {**results[0], "job_ids": [item["job_id"] for item in results],
            "jobs": results, "brief_id": contract.generation_brief_id,
            "instruction": "Report these actual job IDs and statuses. " + ("Continue preparing/queuing the remaining shot IDs from the saved visual plan." if distinct_shots else "These are separate takes of the same verified brief.")}


def _queue_local_take(settings, registry, session_factory, project_id, message_id, workflow_id, index, count):
    from .services import add_event, new_id
    association = "local_render_job_id" if index == 0 else f"local_render_job_id_{index + 1}"

    # Persisted message id provides idempotency even if the AI reply fails after queueing.
    with session_factory() as session:
        source = session.get(Message, message_id)
        conversation = session.get(Conversation, source.conversation_id) if source else None
        if not source or source.role != "user" or not conversation or conversation.project_id != project_id:
            raise ProviderError("A current project user message is required to queue a render")
        if not permission_enabled(session, project_id):
            raise ProviderError("Allow local rendering is off for this project. Use Review generation.")
        existing_id = source.metadata_json.get(association)
        if existing_id:
            existing = session.get(Job, existing_id)
            if not existing or existing.project_id != project_id or existing.input_payload.get("local_render_message_id") != message_id:
                raise ProviderError("Invalid render job association on this message")
    if existing_id:
        return start_result(settings, session_factory, existing_id)
    contract = registry.get(workflow_id)
    if not workflow_id.startswith("assistant-"):
        raise ProviderError("First prepare a workflow copy with the exact requested inputs")
    graph = json.loads(Path(contract.workflow_reference).read_text(encoding="utf-8"))
    seed_overrides = {}
    if count > 1:
        from .generation_identity import prepare_seeds
        from .workflows import resolve_graph_slot
        original = json.loads(json.dumps(graph))
        prepare_seeds(graph)
        for field in contract.required_inputs:
            node_id, key = resolve_graph_slot(graph, field.maps_to.slot)
            if graph[node_id]["inputs"][key] != original[node_id]["inputs"][key]:
                seed_overrides[field.key] = graph[node_id]["inputs"][key]
    verify_local_graph(settings, contract, graph)
    inputs = contract.validate_inputs(seed_overrides)
    from .render_preview import preview_contract
    render_preview = preview_contract(contract, inputs)
    if render_preview["blocked"]:
        raise ProviderError(render_preview["warnings"][0])
    job_id = new_id()
    directory = settings.data_dir / "jobs" / job_id
    directory.mkdir(parents=True)
    snapshot = directory / "local-graph.json"
    snapshot.write_text(json.dumps(graph), encoding="utf-8")
    saved_contract = contract.model_copy(update={"workflow_reference": str(snapshot)})
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    with session_factory.begin() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        source = session.get(Message, message_id)
        if not permission_enabled(session, project_id):
            raise ProviderError("Local rendering permission was turned off")
        existing_id = source.metadata_json.get(association)
        if not existing_id:
            for asset_id in contract.source_asset_ids:
                asset = session.get(Asset, asset_id)
                if not asset or asset.project_id != project_id:
                    raise ProviderError("Workflow source asset does not belong to this project")
            job = Job(id=job_id, project_id=project_id, provider=contract.execution_provider,
                      status="queued", status_message="Queued with local rendering permission",
                      input_payload={"workflow_id": workflow_id, "inputs": inputs, "approved": True,
                                     "approval_source": "project_local_rendering",
                                     "render_name": contract.name,
                                     "local_render_contract": saved_contract.model_dump(), "local_graph_sha256": digest,
                                     "local_render_message_id": message_id,
                                     "batch_index": index, "batch_count": count},
                      output_asset_ids=[])
            session.add(job)
            shots = (source.metadata_json.get("visual_plan") or {}).get("shots") or []
            if shots:
                brief = shots[index] if len(shots) > 1 else shots[0]
                job.input_payload = {**job.input_payload, "visual_brief": brief}
            context = source.metadata_json.get("production_context", {})
            if context:
                job.input_payload = {**job.input_payload, "production_context": context}
            session.flush()
            session.add(GenerationRecord(id=new_id(), job_id=job_id, workflow_definition_id=workflow_id,
                        prompt="\n".join(item["value"] for item in render_preview["positive"] if item["value"].strip()) or source.content,
                        parameters=inputs, source_asset_ids=contract.source_asset_ids,
                        provider_response_metadata={}, estimated_cost=0))
            plan = ActionPlan(id=new_id(), project_id=project_id, conversation_id=source.conversation_id,
                              workflow_definition_id=workflow_id, request_text=source.content,
                              provider=contract.execution_provider, inputs=inputs,
                              expected_output={**contract.output.model_dump(), "render_preview": render_preview}, estimated_cost=0, state="queued", job_id=job_id)
            session.add(plan)
            session.flush()
            for previous, following in ((None, "proposed"), ("proposed", "approved"), ("approved", "queued")):
                session.add(ActionPlanTransition(id=new_id(), action_plan_id=plan.id, from_state=previous,
                            to_state=following, reason="Project local rendering permission"))
            source.metadata_json = {**source.metadata_json, association: job_id}
            # Any shot can be queued first; the first actual job anchors status.
            if not source.metadata_json.get("local_render_job_id"):
                source.metadata_json = {**source.metadata_json, "local_render_first_job_id": job_id}
            source.metadata_json = {**source.metadata_json, "local_render_job_ids": [
                source.metadata_json[key] for key in ["local_render_job_id", *[f"local_render_job_id_{n}" for n in range(2, count + 1)]]
                if source.metadata_json.get(key)]}
            add_event(session, project_id, "generation.queued", "job", job_id,
                      {"workflow_id": workflow_id, "approval": "project_local_rendering", "message_id": message_id})
    return start_result(settings, session_factory, existing_id or job_id)


def start_result(settings, session_factory, job_id):
    with session_factory() as session:
        job = session.get(Job, job_id)
        result = {"job_id": job.id, "status": job.status, "instruction": "Report the job status truthfully. Do not queue another job for this message."}
        should_start = job.status == "queued" and permission_enabled(session, job.project_id)
    if should_start:
        try:
            launch_local_job(settings, job_id)
            result["worker"] = "started"
        except OSError:
            result["worker"] = "Could not start the worker. Job remains queued; retry this message."
    return result


def authorized_contract(settings, session, job):
    if not permission_enabled(session, job.project_id):
        raise ProviderError("Local rendering permission was turned off before execution")
    contract = WorkflowContract.model_validate(job.input_payload["local_render_contract"])
    snapshot = Path(contract.workflow_reference)
    if hashlib.sha256(snapshot.read_bytes()).hexdigest() != job.input_payload["local_graph_sha256"]:
        raise ProviderError("Local workflow changed after authorization")
    graph = json.loads(snapshot.read_text(encoding="utf-8"))
    verify_local_graph(settings, contract, graph)
    return contract
