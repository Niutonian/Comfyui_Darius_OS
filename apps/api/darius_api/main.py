from __future__ import annotations

import asyncio
import json
import queue
import shutil
import threading
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .workflow_registration import RecipeRegistrationRequest, RecipeMappingUpdate
from .openai_reasoning import reasoning_levels
from .shot_board import board as shot_board, update_production, ShotProductionUpdate, production_context
from .reply_stream import conversational, reply_stream, streaming
from .database import (
    ActionPlan,
    ActionPlanTransition,
    Asset,
    Base,
    Character,
    CharacterAssetReference,
    Conversation,
    GenerationRecord,
    Job,
    LlmPreference,
    LocalRenderPermission,
    Message,
    Project,
    ProjectEvent,
    Scene,
    Shot,
    ShotProduction,
    Timeline,
    TimelineVersion,
    make_engine,
    make_session_factory,
    utcnow,
)
from .media import ingest_upload
from .media_processing import analyze_media
from .agent_harness import parse_assistant_answer
from .task_control import TaskStopped, recover_interrupted_tasks
from .assistant_context import AssistantContextUpdate, project_memory, scoped_asset_ids, validate_memory, workflow_available
from .database import AssistantMemory
from .ollama_models import discover_ollama_models
from .trusted_workflows import WorkflowPreferences, preferences as workflow_preferences, validate_preferences, route_context
from .providers import (
    BflProvider, DEEPSEEK_MODELS, DeepSeekPlannerProvider, LocalTranscriptionProvider,
    LlamaCppPlannerProvider, LocalTtsProvider, OllamaPlannerProvider, OpenAIPlannerProvider,
    OpenCodePlannerProvider, PlannerProvider, ProviderError, build_planner_provider,
    discover_opencode_models, discover_openai_models, opencode_model_capabilities,
)
from .schemas import (
    ActionPlanTransitionView,
    ActionPlanView,
    AssetProvenanceView,
    AssetView,
    CharacterCreate,
    CharacterView,
    ConversationCreate,
    ConversationPlanRequest,
    AssistantReplyRequest,
    ConversationPlanView,
    ConversationView,
    DerivativeBatchView,
    GenerationRequest,
    HealthView,
    JobRunView,
    JobView,
    LlmSettingsUpdate,
    LlmSettingsView,
    LocalRenderSettings,
    MediaAnalysisRequest,
    MediaAnalysisView,
    MessageCreate,
    MessageView,
    ProjectCreate,
    ProjectUpdate,
    ProjectDetail,
    ProjectEventView,
    ProjectView,
    SceneCreate,
    SceneView,
    ShotCreate,
    ShotView,
    TimelineCreate,
    TimelineProposal,
    TimelineRenderRequest,
    TimelineVersionCreate,
    TimelineVersionView,
    TimelineView,
    WebcamCaptureView,
    WorkflowProposal,
    WorkflowView,
)
from .services import (
    RequestError,
    add_event,
    approve_action_plan,
    cancel_action_plan,
    cancel_job,
    create_action_plan,
    create_media_derivatives,
    create_project,
    create_timeline_version,
    enqueue_request,
    new_id,
    propose_timeline,
    queue_timeline_render,
    register_workflows,
    retry_job,
)
from .timeline_ops import export_otio
from .workflows import WorkflowRegistry
from .comfy_assistant import ComfyAssistantTools, TOOL_DEFINITIONS
from .local_render import permission_enabled


def _executable_ready(command: str) -> bool:
    return Path(command).is_file() if Path(command).is_absolute() else shutil.which(command) is not None


def _request_error(exc: RequestError) -> HTTPException:
    message = str(exc)
    return HTTPException(status_code=404 if "does not exist" in message or "unknown workflow" in message else 409, detail=message)


def create_app(
    settings: Settings | None = None,
    planner_provider: PlannerProvider | None = None,
) -> FastAPI:
    from .command_router import catalog
    catalog()  # Validate the packaged local command grammar before serving requests.
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    registry = WorkflowRegistry(settings.workflow_definitions_dir,
                                 (settings.comfy_workflow_defaults_root, settings.comfy_workflow_root,
                                  settings.workflow_definitions_dir), include_bfl=bool(settings.bfl_api_key))

    def settings_for_llm(provider: str, model: str, reasoning_effort: str = "auto") -> Settings:
        if provider == "deepseek":
            return replace(settings, llm_provider=provider, deepseek_model=model)
        if provider == "ollama":
            return replace(settings, llm_provider=provider, ollama_model=model)
        if provider == "llamacpp":
            return replace(settings, llm_provider=provider, llamacpp_model=model)
        if provider == "opencode":
            return replace(settings, llm_provider=provider, opencode_model=model)
        return replace(settings, llm_provider=provider, openai_planner_model=model, openai_reasoning_effort=reasoning_effort)

    selected_planner = planner_provider or build_planner_provider(settings)
    # Bounded lock stripes serialize retries within this local API process.
    reply_locks = [threading.Lock() for _ in range(64)]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(engine)
        recover_interrupted_tasks(session_factory)
        registry.load()
        register_workflows(session_factory, registry)
        active_planner = selected_planner
        active_selection = {
            "provider": getattr(selected_planner, "provider_name", settings.llm_provider),
            "model": getattr(selected_planner, "model_name", ""),
            "source": "environment",
            "reasoning_effort": settings.openai_reasoning_effort,
        }
        if planner_provider is None:
            with session_factory() as session:
                preference = session.get(LlmPreference, "default")
            if preference and preference.provider in {"openai", "deepseek", "ollama", "llamacpp", "opencode"} and preference.model:
                if preference.provider != "deepseek" or preference.model in DEEPSEEK_MODELS:
                    active_planner = build_planner_provider(
                        settings_for_llm(preference.provider, preference.model, preference.reasoning_effort)
                    )
                    active_selection = {
                        "provider": preference.provider,
                        "model": preference.model,
                        "source": "saved",
                        "reasoning_effort": preference.reasoning_effort,
                    }
        app.state.settings = settings
        from .diagnostics import access_key
        app.state.diagnostic_key = access_key(settings)
        app.state.session_factory = session_factory
        app.state.registry = registry
        app.state.planner_provider = active_planner
        app.state.llm_selection = active_selection
        app.state.bfl_provider = BflProvider(settings)
        app.state.tts_provider = LocalTtsProvider(settings)
        app.state.transcription_provider = LocalTranscriptionProvider(settings)
        # Reconnect to durable queued Canvas work after an API/worker restart.
        # Active jobs are reconciled by the existing recovery service, never replayed here.
        with session_factory() as session:
            queued_canvas = session.scalar(select(Job.id).where(Job.status == "queued",
                Job.input_payload["canvas_generation_id"].as_string().is_not(None)).order_by(Job.created_at).limit(1))
        if queued_canvas:
            from .local_render import launch_local_job
            try:
                launch_local_job(settings, queued_canvas)
            except OSError:
                pass  # Retained as queued; Wake shared worker remains available.
        from .job_recovery import recovery_loop
        recovery_stop = asyncio.Event()
        recovery_task = asyncio.create_task(recovery_loop(session_factory, settings, recovery_stop))
        try:
            yield
        finally:
            recovery_stop.set()
            await recovery_task
            engine.dispose()

    app = FastAPI(title="Darius API", version="0.2.0", lifespan=lifespan)
    from .canvas_api import router as canvas_router
    canvas_routes = canvas_router(settings, session_factory, registry)
    app.include_router(canvas_routes)
    from .prompt_transfer import router as prompt_transfer_router
    app.include_router(prompt_transfer_router(session_factory))
    from .creative_ideas import router as creative_ideas_router
    app.include_router(creative_ideas_router(session_factory))
    @app.middleware("http")
    async def diagnostic_requests(request: Request, call_next):
        from .diagnostics import record
        import time
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            record(settings, "backend", "error", "request_failed", method=request.method,
                   path=request.url.path, error_type=type(exc).__name__)
            raise
        if (response.status_code >= 400 or request.method != "GET") and not request.url.path.endswith("/diagnostics"):
            record(settings, "backend", "error" if response.status_code >= 400 else "info", "request",
                   method=request.method, path=request.url.path, status=response.status_code,
                   elapsed_ms=round((time.monotonic() - started) * 1000))
        return response

    @app.get("/api/v1/diagnostics")
    def diagnostics(request: Request, project_id: str | None = None, logs: bool = False):
        import secrets
        from .diagnostics import access_key
        try:
            current_diagnostic_key = access_key(settings)
        except (OSError, ValueError):
            raise HTTPException(503, 'The local console code file needs repair. Use Console code in the Darius Windows manager.')
        if not secrets.compare_digest(request.headers.get("X-Darius-Diagnostics-Key", "").strip().encode(), current_diagnostic_key.encode()):
            raise HTTPException(401, "Unlock the console with the local diagnostics access code.")
        from .diagnostics import redact, service_snapshot, tail
        failures, activities, jobs = [], [], []
        with request.app.state.session_factory() as session:
            if project_id:
                if not session.get(Project, project_id):
                    raise HTTPException(404, "project does not exist")
                messages = session.scalars(select(Message).join(Conversation, Message.conversation_id == Conversation.id)
                    .where(Conversation.project_id == project_id).order_by(Message.created_at.desc()).limit(60))
                for message in messages:
                    meta = message.metadata_json or {}
                    task = meta.get("task") or {}
                    if task.get("state") == "failed":
                        failures.append({"id": message.id, "source": "model", "time": message.created_at.isoformat(),
                            "detail": redact(task.get("error") or "Reply interrupted")})
                    if logs and meta.get("activity_history"):
                        activities.append({"message_id": message.id, "activity": meta["activity_history"][-20:]})
                jobs = list(session.scalars(select(Job).where(Job.project_id == project_id)
                    .order_by(Job.created_at.desc()).limit(20)))
                for job in jobs:
                    if job.status == "failed":
                        failures.append({"id": job.id, "source": "comfyui" if "comfy" in job.provider else "backend",
                            "time": job.created_at.isoformat(), "detail": redact(job.error_detail or job.status_message)})
        failures.sort(key=lambda item: item["time"], reverse=True)
        selection = request.app.state.llm_selection
        result = {"generated_at": utcnow().isoformat(), "project_id": project_id,
                  "provider": selection.get("provider"), "model": selection.get("model"),
                  "failures": failures[:20], "checks": [], "logs": {}, "activities": activities[:10]}
        result["checks"], comfy_text = service_snapshot(settings, selection.get("provider"), logs)
        if logs:
            backend_log = tail(settings.data_dir / "diagnostics" / "backend.jsonl")
            worker_events = "\n".join(line for line in backend_log.splitlines() if '"source": "worker"' in line)
            result["logs"] = {"backend": backend_log, "comfyui": comfy_text,
                "jobs": "\n".join(f"Job {job.id} ({job.status})\n" + tail(settings.data_dir / "jobs" / job.id / "worker.log", 12000) for job in jobs[:3])}
            result["logs"]["jobs"] += "\n" + worker_events
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Accept", "X-Darius-Diagnostics-Key"],
        )

    @app.get("/api/v1/health", response_model=HealthView, response_model_exclude_none=True)
    def health(request: Request) -> dict:
        components: dict[str, dict[str, object]] = {"api": {"ready": True}}
        available_workflows = registry.enabled()
        components["workflows"] = {"ready": bool(available_workflows), "configured": True,
            "detail": f"{len(available_workflows)} available; {len(registry.issues)} invalid definitions excluded"
            + ("; " + "; ".join(issue["file"] + ": " + issue["error"] for issue in registry.issues[:3]) if registry.issues else "")}
        try:
            with request.app.state.session_factory() as session:
                session.execute(text("SELECT 1"))
            components["database"] = {"ready": True}
        except Exception as exc:
            components["database"] = {"ready": False, "detail": type(exc).__name__}
        for name, command in (("ffmpeg", settings.ffmpeg_path), ("ffprobe", settings.ffprobe_path)):
            components[name] = {"ready": _executable_ready(command), "configured": bool(command)}
        comfy_mcp_ready = _executable_ready(settings.comfy_mcp_command)
        components["comfy_mcp"] = {
            "ready": comfy_mcp_ready and settings.comfy_workflow_root is not None,
            "configured": bool(settings.comfy_mcp_command and settings.comfy_workflow_root),
        }
        try:
            with urllib.request.urlopen(f"{settings.comfyui_base_url}/system_stats", timeout=2) as response:
                components["comfyui"] = {"ready": response.status == 200, "configured": True}
        except OSError as exc:
            components["comfyui"] = {"ready": False, "configured": bool(settings.comfyui_base_url), "detail": type(exc).__name__}
        selected_provider = request.app.state.planner_provider
        selected_name = getattr(selected_provider, "provider_name", "custom")
        selected_model = request.app.state.llm_selection.get("model", "")
        openai_model = selected_model if selected_name == "openai" else settings.openai_planner_model
        deepseek_model = selected_model if selected_name == "deepseek" else settings.deepseek_model
        ollama_model = selected_model if selected_name == "ollama" else settings.ollama_model
        llamacpp_model = selected_model if selected_name == "llamacpp" else settings.llamacpp_model
        opencode_model = selected_model if selected_name == "opencode" else settings.opencode_model
        openai_configured = bool(settings.openai_api_key or openai_model)
        deepseek_configured = bool(settings.deepseek_api_key or deepseek_model)
        components["openai"] = {
            "ready": OpenAIPlannerProvider(settings_for_llm("openai", openai_model)).ready(),
            "configured": openai_configured,
            "optional": True,
        }
        components["deepseek"] = {
            "ready": DeepSeekPlannerProvider(settings_for_llm("deepseek", deepseek_model)).ready(),
            "configured": deepseek_configured,
            "optional": True,
        }
        components["ollama"] = {
            "ready": OllamaPlannerProvider(settings_for_llm("ollama", ollama_model)).ready(),
            "configured": bool(ollama_model),
            "optional": True,
        }
        components["llamacpp"] = {
            "ready": LlamaCppPlannerProvider(settings_for_llm("llamacpp", llamacpp_model)).ready(),
            "configured": bool(llamacpp_model),
            "optional": True,
        }
        components["opencode"] = {
            "ready": OpenCodePlannerProvider(settings_for_llm("opencode", opencode_model)).ready(),
            "configured": bool(opencode_model),
            "optional": True,
        }
        selected_configured = {
            "openai": openai_configured,
            "deepseek": deepseek_configured,
            "ollama": bool(ollama_model),
            "llamacpp": bool(llamacpp_model),
            "opencode": bool(opencode_model),
        }.get(selected_name, selected_provider.ready())
        components["llm"] = {
            "ready": selected_provider.ready(),
            "configured": selected_configured,
            "optional": True,
            "detail": selected_name,
        }
        components["bfl"] = {
            "ready": request.app.state.bfl_provider.ready(),
            "configured": bool(settings.bfl_api_key or settings.bfl_api_base_url),
            "optional": True,
        }
        components["tts"] = {
            "ready": app.state.tts_provider.ready(),
            "configured": bool(settings.tts_provider), "optional": True,
        }
        transcription_model_ready = bool(settings.transcription_model_path and settings.transcription_model_path.exists())
        components["transcription"] = {
            "ready": bool(settings.transcription_provider and transcription_model_ready),
            "configured": bool(settings.transcription_provider and (settings.transcription_model or settings.transcription_model_path)),
            "optional": True,
        }
        return {"status": "ok" if components["database"]["ready"] else "degraded", "components": components}

    def llm_settings_payload(request: Request) -> dict:
        selection = request.app.state.llm_selection
        provider = selection["provider"]
        model = selection["model"]
        openai_models = list(discover_openai_models(settings))
        if provider == "openai" and model and model not in openai_models:
            openai_models.append(model)
        providers = [
            {
                "id": "openai",
                "label": "OpenAI",
                "models": openai_models,
                "reasoning_efforts": {name: reasoning_levels(name) for name in openai_models},
                "credential_configured": bool(settings.openai_api_key),
            },
            {
                "id": "deepseek",
                "label": "DeepSeek",
                "models": list(DEEPSEEK_MODELS),
                "credential_configured": bool(settings.deepseek_api_key),
            },
            {
                "id": "ollama",
                "label": "Ollama (local)",
                "models": list(discover_ollama_models(settings)),
                "credential_configured": True,
            },
            {
                "id": "llamacpp",
                "label": "llama.cpp (local)",
                "models": [settings.llamacpp_model],
                "credential_configured": True,
            },
            {
                "id": "opencode",
                "label": "OpenCode Free",
                "models": list(discover_opencode_models(settings)),
                "model_capabilities": opencode_model_capabilities(settings),
                "credential_configured": True,
            },
        ]
        credential_configured = provider in {"ollama", "llamacpp", "opencode"} or bool(
            settings.openai_api_key if provider == "openai" else settings.deepseek_api_key
        )
        return {
            "provider": provider,
            "model": model,
            "ready": request.app.state.planner_provider.ready(),
            "credential_configured": credential_configured,
            "source": selection["source"],
            "reasoning_effort": selection.get("reasoning_effort", "auto"),
            "providers": providers,
        }

    @app.get("/api/v1/settings/llm", response_model=LlmSettingsView)
    def get_llm_settings(request: Request):
        return llm_settings_payload(request)

    @app.post("/api/v1/settings/llm/{provider}/models/refresh")
    def refresh_llm_models(provider: Literal["openai", "opencode", "ollama"]):
        try:
            discovery = {"openai": discover_openai_models, "opencode": discover_opencode_models, "ollama": discover_ollama_models}[provider]
            models = discovery(settings, refresh=True, strict=True)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"id": provider, "label": {"openai": "OpenAI", "opencode": "OpenCode Free", "ollama": "Ollama (local)"}[provider], "models": list(models),
                "credential_configured": bool(settings.openai_api_key) if provider == "openai" else True,
                "model_capabilities": opencode_model_capabilities(settings) if provider == "opencode" else {},
                "reasoning_efforts": {name: reasoning_levels(name) for name in models} if provider == "openai" else {}}

    @app.post("/api/v1/settings/llm", response_model=LlmSettingsView)
    def set_llm_settings(payload: LlmSettingsUpdate, request: Request):
        if payload.provider == "deepseek" and payload.model not in DEEPSEEK_MODELS:
            raise HTTPException(422, "unsupported DeepSeek model")
        if payload.provider == "ollama":
            try:
                installed = discover_ollama_models(settings, refresh=True, strict=True)
            except ProviderError as exc:
                raise HTTPException(502, str(exc)) from exc
            if payload.model not in installed:
                raise HTTPException(422, "This Ollama model is not installed. Refresh the model list and select a downloaded model.")
        if payload.provider == "llamacpp" and payload.model != settings.llamacpp_model:
            raise HTTPException(422, "unsupported llama.cpp model")
        if payload.provider == "opencode" and payload.model not in discover_opencode_models(settings):
            raise HTTPException(422, "unsupported OpenCode free model")
        effort = request.app.state.llm_selection.get("reasoning_effort", "auto")
        if payload.provider == "openai":
            if payload.reasoning_effort is not None:
                effort = payload.reasoning_effort
                if effort not in reasoning_levels(payload.model):
                    raise HTTPException(422, "Unsupported thinking level for this OpenAI model. Choose Model default or a listed level.")
            elif effort not in reasoning_levels(payload.model):
                effort = "auto"
        elif payload.reasoning_effort is not None:
            raise HTTPException(422, "Thinking levels are only configurable for OpenAI models")
        new_planner = build_planner_provider(
            settings_for_llm(payload.provider, payload.model, effort)
        )
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            preference = session.get(LlmPreference, "default")
            if preference is None:
                preference = LlmPreference(id="default", provider=payload.provider, model=payload.model)
                session.add(preference)
            else:
                preference.provider = payload.provider
                preference.model = payload.model
                preference.updated_at = utcnow()
            preference.reasoning_effort = effort
        request.app.state.planner_provider = new_planner
        request.app.state.llm_selection = {
            "provider": payload.provider,
            "model": payload.model,
            "source": "saved",
            "reasoning_effort": effort,
        }
        return llm_settings_payload(request)

    @app.post("/api/v1/live/session")
    async def create_live_session(request: Request):
        """Exchange a browser WebRTC offer for a GPT-Live answer.

        The OpenAI project key remains server-side; the browser receives only
        the opaque Live session response and SDP answer.
        """
        if not settings.openai_api_key:
            raise HTTPException(503, "GPT-Live is unavailable until OPENAI_API_KEY is configured")
        try:
            payload = await request.json()
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "A JSON SDP offer is required") from exc
        sdp = payload.get("sdp") if isinstance(payload, dict) else None
        if not isinstance(sdp, str) or not sdp.strip() or len(sdp) > 1_000_000:
            raise HTTPException(400, "An SDP offer is required")
        project_id = payload.get("project_id") if isinstance(payload, dict) else None
        project_context = ""
        if project_id is not None:
            if not isinstance(project_id, str) or not project_id.strip():
                raise HTTPException(400, "project_id must be a non-empty string")
            with request.app.state.session_factory() as session:
                project = session.get(Project, project_id)
                if not project:
                    raise HTTPException(404, "project does not exist")
                active_jobs = list(session.scalars(select(Job).where(Job.project_id == project_id, Job.status.in_(["queued", "running"])).order_by(Job.created_at.desc()).limit(8)))
                project_context = (f" The active project is {project.name!r} (id {project.id})."
                                   f" Current local jobs: {', '.join(f'{job.id} {job.status}' for job in active_jobs) or 'none'}."
                                   " Every spoken request is forwarded to the project-aware creative helper for ideas and prompt writing. Chat cannot modify boards or launch renders; Use in board applies a prompt and Generate on that board starts rendering.")
        body = json.dumps({
            "session": {
                "type": "live",
                "model": settings.openai_live_model,
                "instructions": (
                    "You are Darius, a concise and warm creative operating system. "
                    "Speak naturally, acknowledge when work is being delegated, and never claim a render "
                    "started or finished unless the application confirms it. Keep all decisions scoped to the active project; never infer assets or jobs from another project." + project_context
                ),
            },
            "transport": {"type": "webrtc", "sdp": sdp},
        }).encode("utf-8")
        outbound = urllib.request.Request(
            "https://api.openai.com/v1/live/sessions", data=body,
            headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(outbound, timeout=30) as response:
                return JSONResponse(status_code=response.status, content=json.loads(response.read().decode("utf-8")))
        except urllib.error.HTTPError as exc:
            detail = "GPT-Live session creation failed"
            try:
                error_body = json.loads(exc.read().decode("utf-8"))
                if isinstance(error_body, dict) and isinstance(error_body.get("error"), dict):
                    detail = str(error_body["error"].get("message") or detail)[:500]
            except (ValueError, OSError):
                pass
            raise HTTPException(exc.code, detail) from exc
        except (OSError, TimeoutError) as exc:
            raise HTTPException(502, "GPT-Live session creation timed out") from exc

    @app.get("/api/v1/projects/{project_id}/local-rendering", response_model=LocalRenderSettings)
    def local_render_settings(project_id: str):
        with session_factory() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            return {"enabled": permission_enabled(session, project_id)}

    @app.post("/api/v1/projects/{project_id}/local-rendering", response_model=LocalRenderSettings)
    def set_local_render_settings(project_id: str, payload: LocalRenderSettings):
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            permission = session.get(LocalRenderPermission, project_id)
            if permission is None:
                permission = LocalRenderPermission(project_id=project_id)
                session.add(permission)
            permission.enabled = payload.enabled
            add_event(session, project_id, "local_rendering.permission_changed", "project", project_id, {"enabled": payload.enabled})
            return payload

    @app.post("/api/v1/projects", response_model=ProjectView, status_code=201)
    def projects_create(payload: ProjectCreate, request: Request):
        values = payload.model_dump()
        name, description = values.pop("name").strip(), values.pop("description")
        return create_project(request.app.state.session_factory, name, description, **values)

    @app.get("/api/v1/projects", response_model=list[ProjectView])
    def projects_list(request: Request):
        with request.app.state.session_factory() as session:
            return list(session.scalars(select(Project).order_by(Project.updated_at.desc(), Project.name)))

    @app.delete("/api/v1/projects/{project_id}", status_code=204)
    def projects_delete(project_id: str, request: Request):
        with request.app.state.session_factory.begin() as session:
            project = session.get(Project, project_id)
            if not project:
                raise HTTPException(404, "project does not exist")
            paths = list(session.scalars(select(Asset.path).where(Asset.project_id == project_id)))
            conversation_ids = list(session.scalars(select(Conversation.id).where(Conversation.project_id == project_id)))
            job_ids = list(session.scalars(select(Job.id).where(Job.project_id == project_id)))
            timeline_ids = list(session.scalars(select(Timeline.id).where(Timeline.project_id == project_id)))
            if conversation_ids:
                session.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
            session.execute(delete(ActionPlanTransition).where(ActionPlanTransition.action_plan_id.in_(select(ActionPlan.id).where(ActionPlan.project_id == project_id))))
            session.execute(delete(ActionPlan).where(ActionPlan.project_id == project_id))
            if timeline_ids:
                session.execute(delete(TimelineVersion).where(TimelineVersion.timeline_id.in_(timeline_ids)))
            session.execute(delete(Timeline).where(Timeline.project_id == project_id))
            if job_ids:
                session.execute(delete(GenerationRecord).where(GenerationRecord.job_id.in_(job_ids)))
            session.execute(delete(CharacterAssetReference).where(CharacterAssetReference.character_id.in_(select(Character.id).where(Character.project_id == project_id))))
            session.execute(update(Shot).where(Shot.scene_id.in_(select(Scene.id).where(Scene.project_id == project_id))).values(selected_asset_id=None))
            session.execute(delete(Asset).where(Asset.project_id == project_id))
            session.execute(delete(ShotProduction).where(ShotProduction.shot_id.in_(select(Shot.id).where(Shot.scene_id.in_(select(Scene.id).where(Scene.project_id == project_id))))))
            session.execute(delete(Shot).where(Shot.scene_id.in_(select(Scene.id).where(Scene.project_id == project_id))))
            session.execute(delete(Scene).where(Scene.project_id == project_id))
            session.execute(delete(Character).where(Character.project_id == project_id))
            session.execute(delete(Conversation).where(Conversation.project_id == project_id))
            session.execute(delete(ProjectEvent).where(ProjectEvent.project_id == project_id))
            session.execute(delete(LocalRenderPermission).where(LocalRenderPermission.project_id == project_id))
            session.execute(delete(Job).where(Job.project_id == project_id))
            session.execute(delete(AssistantMemory).where(AssistantMemory.project_id == project_id))
            session.delete(project)
        for path in paths:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        return None

    @app.get("/api/v1/projects/{project_id}", response_model=ProjectDetail)
    def projects_get(project_id: str, request: Request):
        with request.app.state.session_factory() as session:
            project = session.get(Project, project_id)
            if not project:
                raise HTTPException(404, "project does not exist")
            result = ProjectView.model_validate(project).model_dump()
            result.update(
                character_count=session.scalar(select(func.count()).select_from(Character).where(Character.project_id == project_id)) or 0,
                scene_count=session.scalar(select(func.count()).select_from(Scene).where(Scene.project_id == project_id)) or 0,
                asset_count=session.scalar(select(func.count()).select_from(Asset).where(Asset.project_id == project_id)) or 0,
            )
            return result

    @app.patch("/api/v1/projects/{project_id}", response_model=ProjectView)
    def projects_update(project_id: str, payload: ProjectUpdate, request: Request):
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, "at least one project field is required")
        with request.app.state.session_factory.begin() as session:
            project = session.get(Project, project_id)
            if not project:
                raise HTTPException(404, "project does not exist")
            for key, value in changes.items():
                setattr(project, key, value.strip() if isinstance(value, str) else value)
            if not project.name:
                raise HTTPException(422, "project name cannot be empty")
            project.updated_at = utcnow()
            add_event(session, project_id, "project.updated", "project", project_id, changes)
            return project

    def character_view(session, character: Character) -> dict:  # noqa: ANN001
        value = CharacterView.model_validate(character).model_dump()
        value["approved_reference_asset_ids"] = list(session.scalars(
            select(CharacterAssetReference.asset_id).where(
                CharacterAssetReference.character_id == character.id,
                CharacterAssetReference.approved.is_(True),
            )
        ))
        return value

    @app.post("/api/v1/projects/{project_id}/characters", response_model=CharacterView, status_code=201)
    def characters_create(project_id: str, payload: CharacterCreate, request: Request):
        with request.app.state.session_factory.begin() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            references = payload.approved_reference_asset_ids
            assets = list(session.scalars(select(Asset).where(Asset.id.in_(references)))) if references else []
            if len(assets) != len(set(references)) or any(asset.project_id != project_id for asset in assets):
                raise HTTPException(409, "reference assets must exist in the project")
            character = Character(
                id=new_id(), project_id=project_id, name=payload.name.strip(),
                description=payload.description, canonical_prompt=payload.canonical_prompt,
                negative_prompt=payload.negative_prompt, continuity_notes=payload.continuity_notes,
                voice_profile_id=payload.voice_profile_id, metadata_json=payload.metadata,
            )
            session.add(character)
            session.flush()
            for asset_id in dict.fromkeys(references):
                session.add(CharacterAssetReference(character_id=character.id, asset_id=asset_id, approved=True))
            add_event(session, project_id, "character.created", "character", character.id, {"name": character.name})
            try:
                session.flush()
            except IntegrityError as exc:
                raise HTTPException(409, "character name already exists in project") from exc
            return character_view(session, character)

    @app.get("/api/v1/projects/{project_id}/characters", response_model=list[CharacterView])
    def characters_list(project_id: str, request: Request):
        with request.app.state.session_factory() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            return [character_view(session, item) for item in session.scalars(select(Character).where(Character.project_id == project_id).order_by(Character.name))]

    @app.patch("/api/v1/projects/{project_id}/characters/{character_id}", response_model=CharacterView)
    def characters_update(project_id: str, character_id: str, payload: CharacterCreate, request: Request):
        with request.app.state.session_factory.begin() as session:
            character = session.get(Character, character_id)
            if not character or character.project_id != project_id:
                raise HTTPException(404, "character does not exist in this project")
            refs = payload.approved_reference_asset_ids
            assets = list(session.scalars(select(Asset).where(Asset.id.in_(refs)))) if refs else []
            if len(assets) != len(set(refs)) or any(a.project_id != project_id or a.kind != "image" for a in assets):
                raise HTTPException(409, "reference assets must be images in the project")
            for key, value in payload.model_dump(exclude={"approved_reference_asset_ids", "metadata"}).items():
                setattr(character, key, value)
            character.metadata_json = payload.metadata
            session.query(CharacterAssetReference).filter(CharacterAssetReference.character_id == character_id).delete()
            for asset_id in dict.fromkeys(refs):
                session.add(CharacterAssetReference(character_id=character_id, asset_id=asset_id, approved=True))
            character.updated_at = utcnow()
            add_event(session, project_id, "character.updated", "character", character_id, {"name": character.name})
            return character_view(session, character)

    @app.post("/api/v1/projects/{project_id}/scenes", response_model=SceneView, status_code=201)
    def scenes_create(project_id: str, payload: SceneCreate, request: Request):
        with request.app.state.session_factory.begin() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            scene = Scene(id=new_id(), project_id=project_id, **payload.model_dump())
            session.add(scene)
            add_event(session, project_id, "scene.created", "scene", scene.id, {"number": scene.number})
            try:
                session.flush()
            except IntegrityError as exc:
                raise HTTPException(409, "scene number already exists in project") from exc
            return scene

    @app.get("/api/v1/projects/{project_id}/scenes", response_model=list[SceneView])
    def scenes_list(project_id: str, request: Request):
        with request.app.state.session_factory() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            return list(session.scalars(select(Scene).where(Scene.project_id == project_id).order_by(Scene.number)))

    @app.patch("/api/v1/projects/{project_id}/scenes/{scene_id}", response_model=SceneView)
    def scenes_update(project_id: str, scene_id: str, payload: SceneCreate, request: Request):
        with request.app.state.session_factory.begin() as session:
            scene = session.get(Scene, scene_id)
            if not scene or scene.project_id != project_id:
                raise HTTPException(404, "scene does not exist in this project")
            for key, value in payload.model_dump().items():
                setattr(scene, key, value)
            scene.updated_at = utcnow()
            add_event(session, project_id, "scene.updated", "scene", scene_id, {"number": scene.number})
            return scene

    @app.post("/api/v1/scenes/{scene_id}/shots", response_model=ShotView, status_code=201)
    def shots_create(scene_id: str, payload: ShotCreate, request: Request):
        with request.app.state.session_factory.begin() as session:
            scene = session.get(Scene, scene_id)
            if not scene:
                raise HTTPException(404, "scene does not exist")
            if payload.selected_asset_id:
                asset = session.get(Asset, payload.selected_asset_id)
                if not asset or asset.project_id != scene.project_id:
                    raise HTTPException(409, "selected asset must exist in the scene project")
            shot = Shot(id=new_id(), scene_id=scene_id, **payload.model_dump())
            session.add(shot)
            add_event(session, scene.project_id, "shot.created", "shot", shot.id, {"number": shot.number})
            try:
                session.flush()
            except IntegrityError as exc:
                raise HTTPException(409, "shot number already exists in scene") from exc
            return shot

    @app.get("/api/v1/scenes/{scene_id}/shots", response_model=list[ShotView])
    def shots_list(scene_id: str, request: Request):
        with request.app.state.session_factory() as session:
            if not session.get(Scene, scene_id):
                raise HTTPException(404, "scene does not exist")
            return list(session.scalars(select(Shot).where(Shot.scene_id == scene_id).order_by(Shot.number)))

    @app.patch("/api/v1/scenes/{scene_id}/shots/{shot_id}", response_model=ShotView)
    def shots_update(scene_id: str, shot_id: str, payload: ShotCreate, request: Request):
        with request.app.state.session_factory.begin() as session:
            scene = session.get(Scene, scene_id)
            shot = session.get(Shot, shot_id)
            if not scene or not shot or shot.scene_id != scene_id:
                raise HTTPException(404, "shot does not exist in this scene")
            if payload.selected_asset_id:
                asset = session.get(Asset, payload.selected_asset_id)
                if not asset or asset.project_id != scene.project_id:
                    raise HTTPException(409, "selected asset must exist in the scene project")
            for key, value in payload.model_dump().items():
                setattr(shot, key, value)
            shot.updated_at = utcnow()
            add_event(session, scene.project_id, "shot.updated", "shot", shot_id, {"number": shot.number})
            return shot

    @app.get("/api/v1/projects/{project_id}/shot-board")
    def production_board(project_id: str, request: Request):
        with session_factory() as session:
            return shot_board(session, project_id)

    @app.patch("/api/v1/projects/{project_id}/shot-board/{shot_id}", response_model=ShotView)
    def production_board_update(project_id: str, shot_id: str, payload: ShotProductionUpdate, request: Request):
        with session_factory.begin() as session:
            shot = update_production(session, project_id, shot_id, payload)
            shot.updated_at = utcnow()
            add_event(session, project_id, "shot.production_updated", "shot", shot_id)
            return shot

    @app.get("/api/v1/workflows", response_model=list[WorkflowView])
    def workflows_list(request: Request, project_id: str | None = None) -> list[dict]:
        with session_factory() as session:
            return [contract.public_dict() for contract in request.app.state.registry.enabled() if workflow_available(session, project_id, contract)]

    @app.get("/api/v1/projects/{project_id}/trusted-workflows")
    def trusted_workflows_get(project_id: str):
        with session_factory() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            saved = workflow_preferences(session, project_id)
            from .trusted_workflows import available_recipes
            available = set(available_recipes(session, project_id, registry, settings))
            from .trusted_workflows import global_preferences
            return {**saved.model_dump(), "unavailable_ids": sorted({e.workflow_id for e in saved.entries if e.workflow_id not in available}),
                    "global_defaults": global_preferences(session).model_dump()}

    @app.put("/api/v1/projects/{project_id}/trusted-workflows")
    def trusted_workflows_save(project_id: str, body: WorkflowPreferences):
        with session_factory.begin() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            validate_preferences(session, project_id, registry, body, settings)
            record = session.get(AssistantMemory, project_id)
            if not record:
                record = AssistantMemory(project_id=project_id)
                session.add(record)
            record.context_json = {**(record.context_json or {}), "workflow_preferences": body.model_dump()}
            add_event(session, project_id, "workflows.trusted_updated", "project", project_id, {"enabled": body.enabled, "count": len(body.entries)})
            from .trusted_workflows import global_preferences
            return {**body.model_dump(), "unavailable_ids": [], "global_defaults": global_preferences(session).model_dump()}

    @app.get("/api/v1/settings/workflow-defaults")
    def global_workflow_defaults_get():
        from .trusted_workflows import global_preferences, available_recipes
        with session_factory() as session:
            saved = global_preferences(session)
            available = available_recipes(session, None, registry, settings)
            return {**saved.model_dump(), "unavailable_ids": sorted({entry.workflow_id for entry in saved.entries if entry.workflow_id not in available})}

    @app.put("/api/v1/settings/workflow-defaults")
    def global_workflow_defaults_save(body: WorkflowPreferences):
        from .database import GlobalWorkflowPreference
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            validate_preferences(session, None, registry, body, settings)
            saved = session.get(GlobalWorkflowPreference, "default")
            if saved is None:
                saved = GlobalWorkflowPreference(id="default")
                session.add(saved)
            saved.preferences_json = body.model_dump()
            saved.updated_at = utcnow()
        return {**body.model_dump(), "unavailable_ids": []}

    def recipe_catalog():
        from .base_recipes import recipes
        values = list(recipes(settings, registry).values())
        return {"workflows": [recipe.public_dict() for recipe in values],
                "folder": str(settings.comfy_workflow_defaults_root or ""),
                "note": "Reusable bases from the default-workflow folder and cloud operations. Generated project drafts are excluded. Inspection and render approval still apply."}

    @app.get("/api/v1/workflow-recipes")
    def get_workflow_recipes():
        return recipe_catalog()

    @app.post("/api/v1/workflow-recipes/refresh")
    def refresh_workflow_recipes():
        from .workflow_catalog import refresh_conversion_failures
        try:
            refresh_conversion_failures(settings)
        except OSError as exc:
            raise HTTPException(503, "The workflow cache could not be refreshed. Check data-folder permissions and retry; no render was submitted.") from exc
        registry.load()
        return recipe_catalog()

    @app.post("/api/v1/workflow-recipes/register")
    def register_workflow_recipe(payload: RecipeRegistrationRequest):
        from .workflow_registration import source
        if source(settings, payload.workflow_id) is None:
            raise HTTPException(422, "Only base JSON recipes in the default-workflow folder can be registered globally.")
        bridge = ComfyAssistantTools(settings, registry, session_factory)
        result = bridge.call({"operation": "inspect_workflow", "arguments": {
            "workflow_id": payload.workflow_id, "refresh_registration": payload.force}}, 120)
        if result.get("error") or not result.get("recipe_manifest"):
            raise HTTPException(503, result.get("error", "Recipe inspection was incomplete; no render was submitted."))
        return {"workflow_id": payload.workflow_id, **result["recipe_manifest"]}

    @app.post("/api/v1/workflow-recipes/block-party/import", status_code=201)
    def import_block_party_recipe(file: UploadFile):
        from .block_party import import_zip, PackageError, MAX_UPLOAD
        try:
            content = file.file.read(MAX_UPLOAD + 1)
            return import_zip(settings, content)
        except PackageError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Could not save the imported recipe. Check default-folder and data-folder permissions; no render was submitted.") from exc
        finally:
            file.file.close()

    @app.post("/api/v1/workflow-recipes/block-party/readiness")
    def block_party_recipe_readiness(payload: RecipeRegistrationRequest):
        from .block_party import imported, PackageError
        from .block_party_readiness import check_readiness
        if not imported(payload.workflow_id):
            raise HTTPException(422, "Select an imported Block Party recipe.")
        try:
            return check_readiness(settings, payload.workflow_id)
        except PackageError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.put("/api/v1/workflow-recipes/registration")
    def update_workflow_recipe_mapping(payload: RecipeMappingUpdate):
        from .workflow_registration import registered, register
        record = registered(settings, payload.workflow_id)
        if record is None or record["source_digest"] != payload.source_digest:
            raise HTTPException(409, "The recipe changed or has not been inspected. Register its current version first.")
        try:
            contract = register(settings, payload.workflow_id, record["graph"], roles=payload.roles, expected_source=payload.source_digest)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Could not save recipe registration. Check data-folder permissions; no render was submitted.") from exc
        return {"workflow_id": payload.workflow_id, **contract}

    @app.get("/api/v1/bfl/connection")
    def bfl_connection(request: Request):
        provider = request.app.state.bfl_provider
        if not provider.ready():
            return {"configured": False, "authenticated": False, "credits_available": False}
        try:
            credits = provider.credits()
            return {"configured": True, "authenticated": True, "credits_available": credits.get("credits", 0) > 0}
        except ProviderError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/v1/workflows/{workflow_id}/input-options")
    def workflow_input_options(workflow_id: str):
        from .providers import ComfyMcpProvider
        from .workflows import resolve_graph_slot
        try:
            contract = registry.get(workflow_id)
        except KeyError:
            raise HTTPException(404, "workflow does not exist")
        if contract.execution_provider == "bfl" and contract.id.startswith("bfl-flux-3-"):
            from .bfl_catalog import SCHEMAS, MODELS, field_options
            return {key: choices for key, schema in SCHEMAS[MODELS[contract.id][2]]["properties"].items() if (choices := field_options(schema))}
        if contract.execution_provider != "local-comfyui" or not contract.runtime_mapping.api_format:
            return {}
        try:
            graph = json.loads(ComfyMcpProvider(settings)._workflow_path(contract.workflow_reference).read_text(encoding="utf-8"))
            schemas = ComfyMcpProvider(settings).live_node_schemas(graph)
        except (OSError, ValueError, ProviderError) as exc:
            raise HTTPException(503, "Could not load installed ComfyUI options. You can still edit settings manually.") from exc
        result = {}
        for field in contract.required_inputs:
            try:
                node_id, name = resolve_graph_slot(graph, field.maps_to.slot)
                schema = schemas.get(graph[node_id]["class_type"], {}).get("input", {})
                spec = {**schema.get("required", {}), **schema.get("optional", {})}.get(name)
                if isinstance(spec, list) and spec:
                    options = spec[0] if isinstance(spec[0], list) else None
                    if options is None and spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
                        options = spec[1].get("options")
                    if options is None and spec[0] == "COMFY_DYNAMICCOMBO_V3" and len(spec) > 1 and isinstance(spec[1], dict):
                        options = [option.get("key") for option in spec[1].get("options", []) if isinstance(option, dict)]
                    if isinstance(options, list):
                        result[field.key] = [item for item in options if isinstance(item, (str, int, float, bool))]
            except (KeyError, ValueError):
                continue
        return result

    @app.get("/api/v1/projects/{project_id}/workflows", response_model=list[WorkflowView])
    def project_workflows_list(project_id: str, request: Request) -> list[dict]:
        """Return only workflows previously used by this project.

        The global registry remains available for an explicit workflow request,
        while project surfaces use this endpoint to preserve project silos.
        """
        with request.app.state.session_factory() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            ids = list(session.scalars(
                select(GenerationRecord.workflow_definition_id)
                .join(Job, Job.id == GenerationRecord.job_id)
                .where(Job.project_id == project_id)
                .distinct()
            ))
        result = []
        for workflow_id in ids:
            try:
                contract = request.app.state.registry.get(workflow_id)
            except KeyError:
                continue
            if contract.enabled:
                result.append(contract.public_dict())
        return result

    @app.post("/api/v1/workflows/{workflow_id}/preview")
    def workflow_render_preview(workflow_id: str, payload: WorkflowProposal):
        from .render_preview import preview_contract
        from .services import _check_workflow_source_assets
        try:
            contract = registry.get(workflow_id)
            with session_factory() as session:
                if not session.get(Project, payload.project_id):
                    raise HTTPException(404, "project does not exist")
                _check_workflow_source_assets(session, contract, payload.project_id, request_error=True)
                if contract.execution_provider == "bfl":
                    from .bfl_catalog import resolve_media
                    resolve_media(session, payload.project_id, payload.inputs)
            if not contract.enabled:
                raise RequestError("workflow is disabled")
            return preview_contract(contract, payload.inputs, payload.request_text)
        except RequestError as exc:
            raise _request_error(exc) from exc
        except KeyError:
            raise HTTPException(404, "workflow does not exist")
        except (OSError, ValueError):
            raise HTTPException(422, "Could not inspect the final workflow inputs. Check settings and graph availability.")

    @app.post("/api/v1/workflows/{workflow_id}/propose", response_model=ActionPlanView, status_code=201)
    def workflows_propose(workflow_id: str, payload: WorkflowProposal, request: Request):
        try:
            return create_action_plan(request.app.state.session_factory, request.app.state.registry, payload.project_id, workflow_id, payload.request_text, payload.inputs, payload.conversation_id, payload.source_message_id)
        except RequestError as exc:
            raise _request_error(exc) from exc

    @app.post("/api/v1/projects/{project_id}/requests", response_model=JobView, status_code=202)
    def requests_create(project_id: str, payload: GenerationRequest, request: Request):
        try:
            return enqueue_request(request.app.state.session_factory, request.app.state.registry, project_id, payload.workflow_id, payload.request_text, payload.inputs, payload.approved)
        except RequestError as exc:
            raise _request_error(exc) from exc

    @app.get("/api/v1/action-plans/{plan_id}", response_model=ActionPlanView)
    def action_plans_get(plan_id: str, request: Request):
        with request.app.state.session_factory() as session:
            plan = session.get(ActionPlan, plan_id)
            if not plan:
                raise HTTPException(404, "action plan does not exist")
            return plan

    @app.get("/api/v1/action-plans/{plan_id}/transitions", response_model=list[ActionPlanTransitionView])
    def action_plan_transitions(plan_id: str, request: Request):
        with request.app.state.session_factory() as session:
            if not session.get(ActionPlan, plan_id):
                raise HTTPException(404, "action plan does not exist")
            return list(session.scalars(select(ActionPlanTransition).where(ActionPlanTransition.action_plan_id == plan_id).order_by(ActionPlanTransition.created_at, ActionPlanTransition.id)))

    @app.post("/api/v1/action-plans/{plan_id}/approve", response_model=ActionPlanView)
    def action_plans_approve(plan_id: str, request: Request):
        try:
            plan = approve_action_plan(request.app.state.session_factory, request.app.state.registry, plan_id)
            if plan.provider == "local-comfyui" and plan.job_id:
                from .local_render import launch_local_job
                try:
                    launch_local_job(request.app.state.settings, plan.job_id)
                except OSError:
                    with request.app.state.session_factory.begin() as session:
                        job = session.get(Job, plan.job_id)
                        job.status_message = "Queued, but the local worker could not start. Start the Darius worker to continue."
            return plan
        except RequestError as exc:
            raise _request_error(exc) from exc

    @app.post("/api/v1/action-plans/{plan_id}/cancel", response_model=ActionPlanView)
    def action_plans_cancel(plan_id: str, request: Request):
        try:
            return cancel_action_plan(request.app.state.session_factory, plan_id)
        except RequestError as exc:
            raise _request_error(exc) from exc

    @app.get("/api/v1/jobs", response_model=list[JobView])
    def jobs_list(request: Request, project_id: str | None = None, status: str | None = None):
        query = select(Job)
        if project_id:
            query = query.where(Job.project_id == project_id)
        if status:
            query = query.where(Job.status == status)
        with request.app.state.session_factory() as session:
            return list(session.scalars(query.order_by(Job.created_at.desc())))

    @app.get("/api/v1/jobs/{job_id}", response_model=JobView)
    def jobs_get(job_id: str, request: Request):
        with request.app.state.session_factory() as session:
            job = session.get(Job, job_id)
            if not job:
                raise HTTPException(404, "job does not exist")
            return job

    @app.get("/api/v1/jobs/{job_id}/run", response_model=JobRunView)
    def jobs_run(job_id: str, request: Request):
        """Return a stable, human-readable lifecycle for current and historical jobs."""
        with request.app.state.session_factory() as session:
            job = session.get(Job, job_id)
            if not job:
                raise HTTPException(404, "job does not exist")
            generation = session.scalar(select(GenerationRecord).where(GenerationRecord.job_id == job.id))
            plan = session.scalar(select(ActionPlan).where(ActionPlan.job_id == job.id))
            transitions = list(session.scalars(
                select(ActionPlanTransition).where(ActionPlanTransition.action_plan_id == plan.id)
                .order_by(ActionPlanTransition.created_at, ActionPlanTransition.id)
            )) if plan else []
            retry = session.scalar(select(Job).where(Job.retry_of_job_id == job.id).order_by(Job.created_at.desc()))
            terminal = job.status in {"completed", "failed", "cancelled"}
            ingesting = job.status == "running" and job.status_message.lower().startswith("ingesting")
            approved = next((item for item in transitions if item.to_state in {"approved", "queued"}), None)

            def stage(key, label, state, detail, occurred_at=None):
                return {"key": key, "label": label, "state": state, "detail": detail,
                        "occurred_at": occurred_at}

            stages = [
                stage("prepared", "Request prepared", "completed", "Inputs and workflow were saved",
                      generation.created_at if generation else job.created_at),
                stage("authorized", "Authorized", "completed" if approved or job.input_payload.get("approved") else "pending",
                      "Full auto permission or manual review authorized this run" if approved or job.input_payload.get("approved") else "Waiting for approval",
                      approved.created_at if approved else (job.created_at if job.input_payload.get("approved") else None)),
                stage("queued", "Queued", "completed" if job.started_at or terminal else "current",
                      "Job entered the persistent queue", job.created_at),
                stage("rendering", "Rendering", "completed" if terminal or ingesting else "current" if job.status in {"running", "cancelling"} else "pending",
                      job.status_message if job.status in {"running", "cancelling"} and not ingesting else "Provider execution",
                      job.started_at),
                stage("ingesting", "Saving outputs", "completed" if job.status == "completed" else "current" if ingesting else "pending",
                      "Generated media is being copied into project storage", job.heartbeat_at if ingesting else job.completed_at if job.status == "completed" else None),
                stage("finished", "Finished", "completed" if job.status == "completed" else "failed" if job.status == "failed" else "cancelled" if job.status == "cancelled" else "pending",
                      job.error_detail or job.status_message, job.completed_at),
            ]
            error_text = f"{job.error_code or ''} {job.error_detail or ''}".lower()
            recovery_action = recovery_message = None
            can_retry = False
            if job.status == "failed":
                if job.error_code == "WorkerLost":
                    recovery_action = "inspect_provider_queue"
                    recovery_message = "The local worker stopped. Inspect ComfyUI history and saved outputs before explicitly retrying; this job was not resubmitted."
                elif any(word in error_text for word in ("timeout", "timed out")):
                    recovery_action = "inspect_provider_queue"
                    recovery_message = "The provider may still be working. Check ComfyUI history before retrying to avoid a duplicate render."
                elif any(word in error_text for word in ("out of memory", "vram", "cuda")):
                    recovery_action = "free_vram_and_retry"
                    recovery_message = "Free GPU memory or choose a lighter workflow, then retry this saved run."
                    can_retry = True
                elif any(word in error_text for word in ("missing", "not found", "image input", "source asset")):
                    recovery_action = "repair_inputs"
                    recovery_message = "One or more saved inputs are unavailable. Rebind project assets and prepare a fresh run."
                elif any(word in error_text for word in ("validation", "node", "workflow", "schema")):
                    recovery_action = "review_workflow"
                    recovery_message = "The workflow no longer matches the installed nodes. Reinspect it before preparing a fresh run."
                else:
                    recovery_action = "retry"
                    recovery_message = "The request and provenance are saved. You can safely retry the run."
                    can_retry = True
            elif job.status == "cancelled":
                recovery_action = "retry"
                recovery_message = "This run was cancelled before completion and can be queued again."
                can_retry = True
            return {"job_id": job.id,
                    "workflow_id": generation.workflow_definition_id if generation else None,
                    "request_text": generation.prompt if generation else None,
                    "retry_of_job_id": job.retry_of_job_id,
                    "retried_by_job_id": retry.id if retry else None,
                    "recovery_action": recovery_action,
                    "recovery_message": recovery_message,
                    "can_retry": can_retry,
                    "stages": stages}

    @app.post("/api/v1/jobs/{job_id}/cancel", response_model=JobView)
    def jobs_cancel(job_id: str, request: Request):
        try:
            return cancel_job(request.app.state.session_factory, job_id)
        except RequestError as exc:
            raise _request_error(exc) from exc

    @app.post("/api/v1/jobs/{job_id}/retry", response_model=JobView, status_code=201)
    def jobs_retry(job_id: str, request: Request):
        try:
            retried = retry_job(request.app.state.session_factory, job_id)
            if retried.job_type == "timeline_render":
                from .timeline_jobs import start_timeline_job
                return start_timeline_job(request.app.state.session_factory, request.app.state.settings, retried.id)
            return retried
        except RequestError as exc:
            raise _request_error(exc) from exc

    @app.post("/api/v1/jobs/{job_id}/start-render", response_model=JobView)
    def jobs_start_render(job_id: str, request: Request):
        from .timeline_jobs import start_timeline_job
        try:
            return start_timeline_job(request.app.state.session_factory, request.app.state.settings, job_id)
        except RequestError as exc:
            raise _request_error(exc) from exc

    def persist_upload(
        request: Request, file: UploadFile, project_id: str, role: str,
        scene_id: str | None, shot_id: str | None, approval_state: str,
        metadata_updates: dict | None = None,
    ) -> Asset:
        if role not in {"source", "reference"} or approval_state not in {"pending", "approved", "rejected"}:
            raise HTTPException(422, "invalid role or approval state")
        with request.app.state.session_factory() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            if scene_id:
                scene = session.get(Scene, scene_id)
                if not scene or scene.project_id != project_id:
                    raise HTTPException(409, "scene must belong to project")
            if shot_id:
                shot = session.get(Shot, shot_id)
                scene = session.get(Scene, shot.scene_id) if shot else None
                if not scene or scene.project_id != project_id:
                    raise HTTPException(409, "shot must belong to project")
        try:
            media = ingest_upload(file.file, file.filename or "upload", file.content_type, settings, project_id)
        except ValueError as exc:
            raise HTTPException(413 if "size limit" in str(exc) else 422, str(exc)) from exc
        asset = Asset(
            id=new_id(), project_id=project_id, kind=media.kind, role=role, path=str(media.path),
            content_hash=media.content_hash, mime_type=media.mime_type, width=media.width,
            height=media.height, duration=media.duration, fps=media.fps, sample_rate=media.sample_rate,
            parent_asset_ids=[], scene_id=scene_id, shot_id=shot_id, provider="upload",
            workflow_run_id=None, approval_state=approval_state,
            metadata_json={**media.metadata, **(metadata_updates or {})},
        )
        try:
            with request.app.state.session_factory.begin() as session:
                session.add(asset)
                add_event(session, project_id, "asset.created", "asset", asset.id, {"role": role, "content_hash": media.content_hash})
        except Exception:
            media.path.unlink(missing_ok=True)
            raise
        return asset

    @app.post("/api/v1/assets/upload", response_model=AssetView, status_code=201)
    def assets_upload(
        request: Request,
        file: Annotated[UploadFile, File()],
        project_id: Annotated[str, Form()],
        role: Annotated[str, Form()] = "source",
        scene_id: Annotated[str | None, Form()] = None,
        shot_id: Annotated[str | None, Form()] = None,
        approval_state: Annotated[str, Form()] = "pending",
    ):
        return persist_upload(request, file, project_id, role, scene_id, shot_id, approval_state)

    @app.post(
        "/api/v1/assets/webcam-capture", response_model=WebcamCaptureView,
        status_code=201,
    )
    def webcam_capture(
        request: Request,
        file: Annotated[UploadFile, File()],
        project_id: Annotated[str, Form()],
        scene_id: Annotated[str | None, Form()] = None,
        shot_id: Annotated[str | None, Form()] = None,
    ):
        if not file.content_type or not file.content_type.startswith(("video/", "image/")):
            raise HTTPException(422, "webcam capture must be image or video media")
        asset = persist_upload(
            request, file, project_id, "source", scene_id, shot_id, "pending",
            {"capture_source": "webcam"},
        )
        derivatives, warnings = create_media_derivatives(
            request.app.state.session_factory, settings, asset.id
        )
        return {"asset": asset, "derivatives": derivatives, "warnings": warnings}

    @app.post(
        "/api/v1/assets/{asset_id}/derivatives", response_model=DerivativeBatchView,
    )
    def assets_derivatives(asset_id: str, request: Request, thumbnail_only: bool = False):
        try:
            from .services import ensure_media_thumbnail
            process = ensure_media_thumbnail if thumbnail_only else create_media_derivatives
            derivatives, warnings = process(
                request.app.state.session_factory, settings, asset_id
            )
        except RequestError as exc:
            raise _request_error(exc) from exc
        return {"source_asset_id": asset_id, "derivatives": derivatives, "warnings": warnings}

    @app.get("/api/v1/assets", response_model=list[AssetView])
    def assets_search(
        request: Request,
        project_id: str | None = None,
        kind: str | None = None,
        role: str | None = None,
        provider: str | None = None,
        approval_state: str | None = None,
        scene_id: str | None = None,
        shot_id: str | None = None,
        q: str | None = Query(default=None, max_length=200),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        query = select(Asset)
        for column, value in ((Asset.project_id, project_id), (Asset.kind, kind), (Asset.role, role), (Asset.provider, provider), (Asset.approval_state, approval_state), (Asset.scene_id, scene_id), (Asset.shot_id, shot_id)):
            if value:
                query = query.where(column == value)
        if q:
            escaped = q.replace("%", "\\%").replace("_", "\\_")
            query = query.where(or_(
                Asset.content_hash.ilike(f"%{escaped}%", escape="\\"),
                Asset.path.ilike(f"%{escaped}%", escape="\\"),
                func.json_extract(Asset.metadata_json, "$.original_filename").ilike(f"%{escaped}%", escape="\\"),
            ))
        with request.app.state.session_factory() as session:
            return list(session.scalars(query.order_by(Asset.created_at.desc()).limit(limit)))

    @app.get("/api/v1/assets/{asset_id}/content", response_class=FileResponse)
    def assets_content(asset_id: str, request: Request):
        with request.app.state.session_factory() as session:
            asset = session.get(Asset, asset_id)
            if not asset:
                raise HTTPException(404, "asset does not exist")
            stored_path, mime_type = asset.path, asset.mime_type

        try:
            content_path = Path(stored_path).resolve(strict=True)
            content_path.relative_to(settings.data_dir.resolve(strict=True))
        except (OSError, ValueError):
            # Do not reveal whether an invalid path exists outside managed storage.
            raise HTTPException(404, "asset content does not exist") from None
        if not content_path.is_file():
            raise HTTPException(404, "asset content does not exist")
        return FileResponse(
            content_path,
            media_type=mime_type,
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/v1/assets/{asset_id}/audio-preview")
    def assets_audio_preview(asset_id: str, project_id: str, request: Request):
        from .timeline_audio import waveform
        with request.app.state.session_factory() as session:
            asset = session.get(Asset, asset_id)
            if not asset or asset.project_id != project_id:
                raise HTTPException(404, "asset does not exist in this project")
            if asset.kind not in {"audio", "video"}:
                raise HTTPException(422, "audio preview requires an audio or video asset")
            try:
                content_path = Path(asset.path).resolve(strict=True)
                content_path.relative_to(settings.data_dir.resolve(strict=True))
                if not content_path.is_file():
                    raise ValueError("not a file")
            except (OSError, ValueError):
                raise HTTPException(404, "asset content does not exist") from None
        # Release the DB read transaction before bounded CPU decoding.
        try:
            return waveform(asset, settings)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/v1/assets/{asset_id}", response_model=AssetView)
    def assets_get(asset_id: str, request: Request):
        with request.app.state.session_factory() as session:
            asset = session.get(Asset, asset_id)
            if not asset:
                raise HTTPException(404, "asset does not exist")
            return asset

    @app.delete("/api/v1/assets/{asset_id}", status_code=204)
    def assets_delete(asset_id: str, request: Request):
        with request.app.state.session_factory.begin() as session:
            asset = session.get(Asset, asset_id)
            if not asset:
                raise HTTPException(404, "asset does not exist")
            project_id, path = asset.project_id, asset.path
            session.execute(delete(CharacterAssetReference).where(CharacterAssetReference.asset_id == asset_id))
            session.execute(update(Shot).where(Shot.selected_asset_id == asset_id).values(selected_asset_id=None))
            session.delete(asset)
            add_event(session, project_id, "asset.deleted", "asset", asset_id)
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
        return None

    @app.post(
        "/api/v1/assets/{asset_id}/analyze", response_model=MediaAnalysisView,
    )
    def assets_analyze(asset_id: str, payload: MediaAnalysisRequest, request: Request):
        with request.app.state.session_factory() as session:
            asset = session.get(Asset, asset_id)
            if not asset:
                raise HTTPException(404, "asset does not exist")
            if asset.kind not in {"audio", "video"}:
                raise HTTPException(409, "media analysis requires an audio or video asset")
            source, kind, project_id = Path(asset.path), asset.kind, asset.project_id
        facts = analyze_media(source, kind, settings, **payload.model_dump())
        with request.app.state.session_factory.begin() as session:
            asset = session.get(Asset, asset_id)
            if not asset:
                raise HTTPException(404, "asset does not exist")
            asset.metadata_json = {**asset.metadata_json, "media_analysis": facts}
            add_event(session, project_id, "asset.analysis_completed", "asset", asset.id, {
                "silence_count": len(facts["silence"]), "black_count": len(facts["black"]),
                "freeze_count": len(facts["freeze"]), "scene_count": len(facts["scenes"]),
                "warnings": facts["warnings"],
            })
        return {"asset_id": asset_id, "facts": facts}

    @app.get("/api/v1/assets/{asset_id}/provenance", response_model=AssetProvenanceView)
    def assets_provenance(asset_id: str, request: Request) -> dict:
        with request.app.state.session_factory() as session:
            asset = session.get(Asset, asset_id)
            if not asset:
                raise HTTPException(404, "asset does not exist")
            generation = session.scalar(select(GenerationRecord).where(GenerationRecord.job_id == asset.workflow_run_id)) if asset.workflow_run_id else None
            result = {"asset": AssetView.model_validate(asset).model_dump(mode="json"), "generation": None}
            if generation:
                result["generation"] = {
                    "id": generation.id, "job_id": generation.job_id,
                    "workflow_definition_id": generation.workflow_definition_id,
                    "prompt": generation.prompt, "negative_prompt": generation.negative_prompt,
                    "seed": generation.seed, "model": generation.model,
                    "parameters": generation.parameters, "source_asset_ids": generation.source_asset_ids,
                    "provider_response_metadata": generation.provider_response_metadata,
                    "created_at": generation.created_at.isoformat(),
                }
            else:
                result["import"] = {"original_filename": asset.metadata_json.get("original_filename"), "content_hash": asset.content_hash}
            return result

    @app.get("/api/v1/projects/{project_id}/assistant-context")
    def assistant_context_get(project_id: str):
        with session_factory() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            return project_memory(session, project_id)

    @app.put("/api/v1/projects/{project_id}/assistant-context")
    def assistant_context_save(project_id: str, body: AssistantContextUpdate):
        with session_factory.begin() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            data = validate_memory(session, project_id, body)
            record = session.get(AssistantMemory, project_id)
            if not record:
                record = AssistantMemory(project_id=project_id)
                session.add(record)
            data["workflow_preferences"] = (record.context_json or {}).get("workflow_preferences", {})
            record.context_json = data
            add_event(session, project_id, "assistant.context_updated", "project", project_id)
            return data

    @app.post("/api/v1/projects/{project_id}/conversations", response_model=ConversationView, status_code=201)
    def conversations_create(project_id: str, payload: ConversationCreate, request: Request):
        with request.app.state.session_factory.begin() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "project does not exist")
            conversation = Conversation(id=new_id(), project_id=project_id, title=payload.title)
            session.add(conversation)
            add_event(session, project_id, "conversation.created", "conversation", conversation.id)
            return conversation

    @app.get("/api/v1/projects/{project_id}/conversations", response_model=list[ConversationView])
    def conversations_list(project_id: str, request: Request):
        with request.app.state.session_factory() as session:
            return list(session.scalars(select(Conversation).where(Conversation.project_id == project_id).order_by(Conversation.updated_at.desc())))

    @app.patch("/api/v1/projects/{project_id}/conversations/{conversation_id}", response_model=ConversationView)
    def conversation_rename(project_id: str, conversation_id: str, payload: ConversationCreate, request: Request):
        title = payload.title.strip()
        if not title:
            raise HTTPException(422, "Conversation title cannot be blank")
        with session_factory.begin() as session:
            conversation = session.get(Conversation, conversation_id)
            if not conversation or conversation.project_id != project_id:
                raise HTTPException(404, "conversation does not belong to this project")
            conversation.title = title
            conversation.updated_at = utcnow()
            add_event(session, project_id, "conversation.renamed", "conversation", conversation_id)
            return conversation

    @app.delete("/api/v1/projects/{project_id}/conversations/{conversation_id}")
    def conversation_delete(project_id: str, conversation_id: str, request: Request):
        lock = reply_locks[hash(conversation_id) % len(reply_locks)]
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "Wait for the current reply to finish before deleting this chat")
        try:
            with session_factory.begin() as session:
                conversation = session.get(Conversation, conversation_id)
                if not conversation or conversation.project_id != project_id:
                    raise HTTPException(404, "conversation does not belong to this project")
                session.execute(update(ActionPlan).where(ActionPlan.conversation_id == conversation_id).values(conversation_id=None))
                session.execute(delete(Message).where(Message.conversation_id == conversation_id))
                session.delete(conversation)
                add_event(session, project_id, "conversation.deleted", "conversation", conversation_id)
            return {"deleted": conversation_id}
        finally:
            lock.release()

    @app.post("/api/v1/conversations/{conversation_id}/messages", response_model=MessageView, status_code=201)
    def messages_create(conversation_id: str, payload: MessageCreate, request: Request):
        with request.app.state.session_factory.begin() as session:
            conversation = session.get(Conversation, conversation_id)
            if not conversation:
                raise HTTPException(404, "conversation does not exist")
            message = Message(id=new_id(), conversation_id=conversation_id, role=payload.role, content=payload.content, metadata_json=payload.metadata)
            if payload.role == "user":
                message.metadata_json = {**payload.metadata, "production_context": production_context(session, conversation.project_id)}
            session.add(message)
            conversation.updated_at = utcnow()
            add_event(session, conversation.project_id, "conversation.message_created", "message", message.id, {"role": message.role})
            return message

    @app.get("/api/v1/conversations/{conversation_id}/messages", response_model=list[MessageView])
    def messages_list(conversation_id: str, request: Request):
        with request.app.state.session_factory() as session:
            if not session.get(Conversation, conversation_id):
                raise HTTPException(404, "conversation does not exist")
            return list(session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at, Message.id)))

    @app.post("/api/v1/conversations/{conversation_id}/messages/{message_id}/task/{action}", response_model=MessageView)
    def control_assistant_task(conversation_id: str, message_id: str, action: Literal["pause", "resume", "cancel"], request: Request):
        with session_factory.begin() as session:
            source = session.get(Message, message_id)
            conversation = session.get(Conversation, conversation_id)
            if not source or not conversation or source.conversation_id != conversation_id or source.role != "user":
                raise HTTPException(404, "conversation user message does not exist")
            metadata = source.metadata_json
            job_id = metadata.get("local_render_job_id")
            job = session.get(Job, job_id) if job_id else None
            if job and job.project_id != conversation.project_id:
                raise HTTPException(409, "task job does not belong to this project")
            if action == "pause" and job:
                raise HTTPException(409, "The render has already started. Use Cancel render in Background jobs.")
            if action == "resume" and metadata.get("task_control") == "cancel":
                raise HTTPException(409, "This task was cancelled. Send a new request to start again.")
            state = "pause_requested" if action == "pause" else "cancelled" if action == "cancel" else "ready"
            source.metadata_json = {**metadata, "task_control": None if action == "resume" else action,
                "task": {**metadata.get("task", {}), "state": state, "error": ""}}
            add_event(session, conversation.project_id, "assistant.control", "message", source.id, {"action": action})
        if action == "cancel" and job and job.status in {"queued", "running", "cancelling"}:
            try:
                cancel_job(session_factory, job.id)
            except RequestError:
                # The worker may have completed between the read and cancellation.
                with session_factory() as session:
                    latest_job = session.get(Job, job.id)
                    if latest_job and latest_job.status not in {"completed", "failed", "cancelled"}:
                        raise HTTPException(409, "Render cancellation could not be applied. Check Background jobs.")
        with session_factory() as session:
            return session.get(Message, message_id)

    @app.post("/api/v1/conversations/{conversation_id}/messages/{message_id}/retry-preparation", response_model=MessageView)
    def retry_chat_preparation(conversation_id: str, message_id: str):
        lock = reply_locks[hash(conversation_id) % len(reply_locks)]
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "This conversation is still working. Wait for its current step.")
        try:
            with session_factory.begin() as session:
                source = session.get(Message, message_id)
                conversation = session.get(Conversation, conversation_id)
                if not source or not conversation or source.conversation_id != conversation_id or source.role != "user":
                    raise HTTPException(404, "conversation user message does not exist")
                latest = session.scalar(select(Message).where(Message.conversation_id == conversation_id, Message.metadata_json["superseded"].as_boolean().is_not(True)).order_by(Message.created_at.desc(), Message.id.desc()).limit(1))
                already_ready = bool(latest and latest.id == source.id and source.metadata_json.get("preparation_revision", 0) > 0 and source.metadata_json.get("task", {}).get("state") == "ready")
                if not already_ready and (not latest or latest.role != "assistant" or latest.metadata_json.get("reply_to") != source.id):
                    raise HTTPException(409, "Only the latest blocked request can be retried here.")
                if source.metadata_json.get("task_control") == "cancel" or (not already_ready and not latest.metadata_json.get("recovery", {}).get("can_retry")):
                    raise HTTPException(409, "This request needs your input instead. Send the clarification in chat.")
                # Never trust message metadata alone: a persisted job association
                # is authoritative even if its receipt was lost during a restart.
                linked = session.scalar(select(Job.id).where(Job.project_id == conversation.project_id, Job.input_payload["local_render_message_id"].as_string() == source.id).limit(1))
                if linked or source.metadata_json.get("local_render_job_id") or source.metadata_json.get("local_render_job_ids") or source.metadata_json.get("local_render_first_job_id"):
                    raise HTTPException(409, "This request already has renders. Check Background jobs; no duplicate was submitted.")
                if already_ready:
                    return source
                metadata = {key: value for key, value in source.metadata_json.items() if key not in {"visual_plan", "shot_workflows", "activity_history", "tool_activity"}}
                revision = int(metadata.get("preparation_revision", 0)) + 1
                if revision > 20:
                    raise HTTPException(409, "This request has reached its recovery limit. Start a new request after correcting the setup.")
                latest.metadata_json = {**latest.metadata_json, "superseded": True}
                source.metadata_json = {**metadata, "preparation_revision": revision, "task_control": None,
                    "task": {"id": source.id, "state": "ready", "step": "preflight"}}
                add_event(session, conversation.project_id, "assistant.recovery_requested", "message", source.id)
                return source
        finally:
            lock.release()

    @app.post("/api/v1/conversations/{conversation_id}/reply", response_model=MessageView)
    def assistant_reply(conversation_id: str, payload: AssistantReplyRequest, request: Request):
        with reply_locks[hash(conversation_id) % len(reply_locks)]:
            with request.app.state.session_factory() as session:
                conversation = session.get(Conversation, conversation_id)
                source = session.get(Message, payload.message_id)
                if not conversation or not source or source.conversation_id != conversation_id or source.role != "user":
                    raise HTTPException(404, "conversation user message does not exist")
                previous = session.scalar(select(Message).where(Message.conversation_id == conversation_id, Message.role == "assistant", Message.metadata_json["reply_to"].as_string() == source.id, Message.metadata_json["superseded"].as_boolean().is_not(True)))
                if previous:
                    return previous
                if source.metadata_json.get("task_control") in {"pause", "cancel"}:
                    raise HTTPException(409, "Task paused. Resume when ready." if source.metadata_json["task_control"] == "pause" else "Task cancelled.")
                all_messages = list(session.scalars(select(Message).where(Message.conversation_id == conversation_id, Message.metadata_json["superseded"].as_boolean().is_not(True)).order_by(Message.created_at.desc(), Message.id.desc()).limit(40)))
                if all_messages[0].id != source.id:
                    raise HTTPException(409, "Reply to the most recent user message instead")
                project_id = conversation.project_id
                attached_ids = source.metadata_json.get("asset_ids", [])
                if not isinstance(attached_ids, list) or len(attached_ids) > 20 or any(not isinstance(asset_id, str) for asset_id in attached_ids):
                    raise HTTPException(422, "invalid attachment list")
                for asset_id in attached_ids:
                    asset = session.get(Asset, asset_id)
                    if not asset or asset.project_id != project_id:
                        raise HTTPException(422, "attachment does not belong to this project")
                from .asset_presentation import quick_presentation
                presentation = quick_presentation(session, settings, conversation, source, all_messages)
                if presentation is not None:
                    from .command_router import route_command, ENGINE_VERSION
                    decision = route_command(source.content)
                    routing = {"engine": "hassil", "version": ENGINE_VERSION, "intent": decision["intent"], "action": decision["action"]} if decision else None
                    task = {"id": source.id, "engine": "presentation", "state": "replied"}
                    message = Message(id=new_id(), conversation_id=conversation_id, role="assistant", content=presentation["reply"], metadata_json={
                        "reply_to": source.id, "presentation_actions": presentation["actions"], "task": task,
                        "viewed_asset_ids": [], "reference_asset_ids": [], "command_router": routing})
                    source.metadata_json = {**source.metadata_json, "task": task}
                    conversation.updated_at = utcnow()
                    session.add(message)
                    add_event(session, project_id, "conversation.assistant_replied", "message", message.id)
                    session.commit()
                    from .diagnostics import record
                    if routing:
                        record(settings, "backend", "info", "local_command", project_id=project_id, **routing)
                    from .reply_stream import publish
                    publish(message.content)
                    return message
                from .creative_chat import context_for
                context = context_for(session, project_id, all_messages, source.metadata_json.get("canvas_board"))
                provider = request.app.state.planner_provider
                if not provider.ready():
                    raise HTTPException(503, "Darius AI is not configured. Select a model in Settings.")
                task = {"id":source.id,"engine":"creative-helper","state":"running","step":"writing_reply"}
                source.metadata_json = {**source.metadata_json,"task":task}
                add_event(session, project_id, "assistant.task_updated", "message", source.id, task)
                session.commit()
            image_ids = []
            try:
                if context["attached_asset_ids"]:
                    from .assistant_assets import view_project_assets
                    with session_factory() as image_session:
                        image_ids = [key for key in context["attached_asset_ids"] if image_session.get(Asset,key).kind == "image"][:4]
                    if image_ids:
                        context["_creative_images"] = view_project_assets(session_factory, settings, project_id, image_ids)["_image_content"]
                if isinstance(provider, OpenAIPlannerProvider):
                    result = provider.plan(context, source.content, tool_runner=None, tool_definitions=None)
                else:
                    result = provider.plan(context, source.content)
                answer = parse_assistant_answer(result.get("output", []))
                reply = answer["reply"].strip()
                # Stale/custom providers may return old proposals. Retain text
                # only; never resolve workflows or dispatch actions from output.
                legacy_prompt = answer.get("generation_prompt")
                if isinstance(legacy_prompt, str) and legacy_prompt.strip() and len(legacy_prompt) <= 30000 and legacy_prompt not in reply:
                    reply += "\n\n```prompt Prompt draft\n" + legacy_prompt + "\n```"
                from .creative_chat import prompt_drafts
                drafts = prompt_drafts(reply)
            except ProviderError as exc:
                with session_factory.begin() as failed_session:
                    failed = failed_session.get(Message, payload.message_id)
                    if failed:
                        failed.metadata_json = {**failed.metadata_json, "task":{"id":failed.id,"engine":"creative-helper","state":"failed","error":str(exc)}}
                raise HTTPException(409 if isinstance(exc, TaskStopped) else 503, str(exc)) from exc
            except (ValueError, TypeError, AttributeError) as exc:
                raise HTTPException(503, "Darius could not complete this reply. Check the selected model and retry.") from exc
            with session_factory.begin() as session:
                conversation = session.get(Conversation, conversation_id)
                source = session.get(Message, payload.message_id)
                if source.metadata_json.get("task_control") in {"pause","cancel"}:
                    raise HTTPException(409,"This reply was paused or cancelled.")
                task = {"id":source.id,"engine":"creative-helper","state":"replied"}
                message = Message(id=new_id(), conversation_id=conversation_id, role="assistant", content=reply,
                    metadata_json={"reply_to":source.id,"creative_helper":True,"prompt_drafts":drafts,
                        "generation_prompt":None,"workflow_id":None,"viewed_asset_ids":image_ids,
                        "reference_asset_ids":[],"task":task})
                source.metadata_json = {**source.metadata_json,"task":task}
                conversation.updated_at = utcnow()
                session.add(message)
                add_event(session, project_id, "conversation.assistant_replied", "message", message.id)
                return message

    @app.post("/api/v1/conversations/{conversation_id}/reply/stream", response_class=StreamingResponse,
              responses={200: {"content": {"application/x-ndjson": {}}}})
    def assistant_reply_stream(conversation_id: str, payload: AssistantReplyRequest, request: Request):
        events = queue.Queue()
        closed = threading.Event()
        def emit(event):
            if not closed.is_set():
                events.put(event)
        def run():
            try:
                with reply_stream(emit):
                    message = assistant_reply(conversation_id, payload, request)
                emit({"type": "done", "message": MessageView.model_validate(message).model_dump(mode="json")})
            except HTTPException as exc:
                emit({"type": "error", "detail": str(exc.detail), "status": exc.status_code})
            except Exception:
                emit({"type": "error", "detail": "Darius could not complete this reply. Retry the saved message.", "status": 503})
        def generate():
            threading.Thread(target=run, daemon=True).start()
            try:
                while True:
                    try:
                        event = events.get(timeout=5)
                    except queue.Empty:
                        yield '{"type":"keepalive"}\n'
                        continue
                    yield json.dumps(event, ensure_ascii=False) + "\n"
                    if event["type"] in {"done", "error"}:
                        break
            finally:
                closed.set()
        return StreamingResponse(generate(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post(
        "/api/v1/conversations/{conversation_id}/plan",
        response_model=ConversationPlanView,
    )
    def conversation_plan(conversation_id: str, payload: ConversationPlanRequest, request: Request):
        raise HTTPException(410, "Chat now develops ideas and prompts. Use the conversation reply endpoint; Generate is available on boards.")

    @app.get("/api/v1/projects/{project_id}/events", response_model=list[ProjectEventView])
    def project_events(project_id: str, request: Request, limit: int = Query(default=200, ge=1, le=1000)):
        with request.app.state.session_factory() as session:
            return list(session.scalars(select(ProjectEvent).where(ProjectEvent.project_id == project_id).order_by(ProjectEvent.created_at.desc()).limit(limit)))

    @app.get("/api/v1/events/stream")
    async def events_stream(request: Request, project_id: str | None = None, once: bool = False, live: bool = False):
        async def generate():
            cursor = None
            with request.app.state.session_factory() as session:
                previous = session.get(ProjectEvent, request.headers.get("last-event-id", ""))
                if previous and (not project_id or previous.project_id == project_id):
                    cursor = (previous.created_at, previous.id)
                elif live:
                    query = select(ProjectEvent)
                    if project_id:
                        query = query.where(ProjectEvent.project_id == project_id)
                    latest = session.scalar(query.order_by(ProjectEvent.created_at.desc(), ProjectEvent.id.desc()).limit(1))
                    if latest:
                        cursor = (latest.created_at, latest.id)
            if live:
                yield 'event: ready\ndata: {}\n\n'
            while True:
                with request.app.state.session_factory() as session:
                    query = select(ProjectEvent)
                    if project_id:
                        query = query.where(ProjectEvent.project_id == project_id)
                    if cursor:
                        query = query.where(or_(ProjectEvent.created_at > cursor[0],
                                                (ProjectEvent.created_at == cursor[0]) & (ProjectEvent.id > cursor[1])))
                    events = list(session.scalars(query.order_by(ProjectEvent.created_at, ProjectEvent.id).limit(500)))
                    jobs_query = select(Job)
                    if project_id:
                        jobs_query = jobs_query.where(Job.project_id == project_id)
                    jobs = list(session.scalars(jobs_query.order_by(Job.created_at.desc()).limit(100)))
                for event in events:
                    cursor = (event.created_at, event.id)
                    data = ProjectEventView.model_validate(event).model_dump(mode="json")
                    yield f"id: {event.id}\nevent: project_event\ndata: {json.dumps(data)}\n\n"
                snapshot = [{"id": job.id, "status": job.status, "progress": job.progress, "status_message": job.status_message} for job in jobs]
                yield f"event: jobs\ndata: {json.dumps(snapshot)}\n\n"
                if once or await request.is_disconnected():
                    break
                await asyncio.sleep(1.0)
        return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/v1/timelines", response_model=TimelineView, status_code=201)
    def timelines_create(payload: TimelineCreate, request: Request):
        with request.app.state.session_factory.begin() as session:
            if not session.get(Project, payload.project_id):
                raise HTTPException(404, "project does not exist")
            if payload.scene_id:
                scene = session.get(Scene, payload.scene_id)
                if not scene or scene.project_id != payload.project_id:
                    raise HTTPException(409, "scene must belong to project")
            timeline = Timeline(id=new_id(), **payload.model_dump())
            session.add(timeline)
            add_event(session, payload.project_id, "timeline.created", "timeline", timeline.id, {"name": timeline.name})
            return timeline

    @app.get("/api/v1/timelines", response_model=list[TimelineView])
    def timelines_list(request: Request, project_id: str | None = None):
        query = select(Timeline)
        if project_id:
            query = query.where(Timeline.project_id == project_id)
        with request.app.state.session_factory() as session:
            return list(session.scalars(query.order_by(Timeline.updated_at.desc())))

    @app.post("/api/v1/timelines/{timeline_id}/versions", response_model=TimelineVersionView, status_code=201)
    def timeline_versions_create(timeline_id: str, payload: TimelineVersionCreate, request: Request):
        try:
            return create_timeline_version(
                request.app.state.session_factory, timeline_id, payload.tracks,
                payload.state, payload.edit_summary, "user",
            )
        except RequestError as exc:
            raise _request_error(exc) from exc

    @app.get("/api/v1/timelines/{timeline_id}/versions", response_model=list[TimelineVersionView])
    def timeline_versions_list(timeline_id: str, request: Request):
        with request.app.state.session_factory() as session:
            if not session.get(Timeline, timeline_id):
                raise HTTPException(404, "timeline does not exist")
            return list(session.scalars(select(TimelineVersion).where(TimelineVersion.timeline_id == timeline_id).order_by(TimelineVersion.version_number)))

    @app.get(
        "/api/v1/timelines/{timeline_id}/versions/{version_id}/otio",
        response_model=dict[str, object],
    )
    def timeline_version_otio(timeline_id: str, version_id: str, request: Request):
        with request.app.state.session_factory() as session:
            timeline = session.get(Timeline, timeline_id)
            version = session.get(TimelineVersion, version_id)
            if not timeline:
                raise HTTPException(404, "timeline does not exist")
            if not version or version.timeline_id != timeline.id:
                raise HTTPException(404, "timeline version does not exist")
            document = export_otio(session, timeline, version)
        return JSONResponse(document, media_type="application/vnd.pixar.opentimelineio+json")

    @app.post(
        "/api/v1/timelines/{timeline_id}/render", response_model=JobView,
        status_code=202,
    )
    def timeline_render(timeline_id: str, payload: TimelineRenderRequest, request: Request):
        try:
            job = queue_timeline_render(
                request.app.state.session_factory, timeline_id, payload.version_id, payload.approved
            )
            from .timeline_jobs import start_timeline_job
            return start_timeline_job(request.app.state.session_factory, request.app.state.settings, job.id)
        except RequestError as exc:
            raise _request_error(exc) from exc

    @app.post("/api/v1/timelines/{timeline_id}/propose", response_model=TimelineVersionView, status_code=201)
    def timeline_propose(timeline_id: str, payload: TimelineProposal, request: Request):
        try:
            return propose_timeline(request.app.state.session_factory, timeline_id, payload.scene_id)
        except RequestError as exc:
            raise _request_error(exc) from exc

    return app


app = create_app()
