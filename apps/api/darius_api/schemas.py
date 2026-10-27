from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OrmView(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LocalRenderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(strict=True)


class LlmSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["openai", "deepseek", "ollama", "llamacpp", "opencode"]
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    reasoning_effort: Literal["auto", "none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None


class LlmProviderOption(BaseModel):
    id: Literal["openai", "deepseek", "ollama", "llamacpp", "opencode"]
    label: str
    models: list[str]
    credential_configured: bool
    model_capabilities: dict[str, dict[str, bool]] = Field(default_factory=dict)
    reasoning_efforts: dict[str, list[str]] = Field(default_factory=dict)


class LlmSettingsView(BaseModel):
    provider: Literal["openai", "deepseek", "ollama", "llamacpp", "opencode"]
    model: str
    reasoning_effort: str = "auto"
    ready: bool
    credential_configured: bool
    source: Literal["environment", "saved"]
    providers: list[LlmProviderOption]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    creative_brief: str = Field(default="", max_length=20_000)
    visual_style: str = Field(default="", max_length=5000)
    default_aspect_ratio: str = Field(default="16:9", max_length=30)
    default_resolution: str = Field(default="1920x1080", pattern=r"^\d+x\d+$")
    default_fps: float = Field(default=24.0, gt=0, le=240)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


class ProjectView(OrmView):
    id: str
    name: str
    description: str
    creative_brief: str
    visual_style: str
    default_aspect_ratio: str
    default_resolution: str
    default_fps: float
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectView):
    character_count: int = 0
    scene_count: int = 0
    asset_count: int = 0


class CharacterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    canonical_prompt: str = Field(default="", max_length=20_000)
    negative_prompt: str = Field(default="", max_length=20_000)
    continuity_notes: str = Field(default="", max_length=20_000)
    voice_profile_id: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    approved_reference_asset_ids: list[str] = Field(default_factory=list)


class CharacterView(OrmView):
    id: str
    project_id: str
    name: str
    description: str
    canonical_prompt: str
    negative_prompt: str
    continuity_notes: str
    voice_profile_id: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    approved_reference_asset_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SceneCreate(BaseModel):
    number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=20_000)
    screenplay_text: str = Field(default="", max_length=100_000)
    location: str = Field(default="", max_length=300)
    time_of_day: str = Field(default="", max_length=100)
    mood: str = Field(default="", max_length=200)
    status: Literal["draft", "planned", "ready", "complete"] = "draft"


class SceneView(OrmView):
    id: str
    project_id: str
    number: int
    title: str
    description: str
    screenplay_text: str
    location: str
    time_of_day: str
    mood: str
    status: str
    created_at: datetime
    updated_at: datetime


class ShotCreate(BaseModel):
    number: int = Field(ge=1)
    description: str = Field(default="", max_length=20_000)
    shot_type: str = Field(default="", max_length=100)
    camera_motion: str = Field(default="", max_length=100)
    duration_target: float = Field(default=3.0, gt=0, le=3600)
    dialogue: str = Field(default="", max_length=50_000)
    status: Literal["planned", "ready", "generated", "selected", "complete"] = "planned"
    selected_asset_id: str | None = None


class ShotView(OrmView):
    id: str
    scene_id: str
    number: int
    description: str
    shot_type: str
    camera_motion: str
    duration_target: float
    dialogue: str
    status: str
    selected_asset_id: str | None
    created_at: datetime
    updated_at: datetime


class GenerationRequest(BaseModel):
    workflow_id: str
    request_text: str = Field(min_length=1, max_length=20_000)
    inputs: dict[str, Any]
    approved: bool = False


class WorkflowProposal(BaseModel):
    project_id: str
    request_text: str = Field(min_length=1, max_length=20_000)
    inputs: dict[str, Any]
    conversation_id: str | None = None
    source_message_id: str | None = None


class JobView(OrmView):
    display_name: str = "Generation"
    indeterminate_progress: bool = False
    canvas_board_id: str | None = None
    id: str
    project_id: str
    job_type: str
    provider: str
    status: str
    progress: float
    status_message: str
    output_asset_ids: list[str]
    external_job_id: str | None
    error_code: str | None
    error_detail: str | None
    attempt_count: int
    retry_of_job_id: str | None
    cancellation_requested: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class JobRunStageView(BaseModel):
    key: str
    label: str
    state: Literal["pending", "current", "completed", "failed", "cancelled"]
    detail: str
    occurred_at: datetime | None = None


class JobRunView(BaseModel):
    job_id: str
    workflow_id: str | None
    request_text: str | None
    retry_of_job_id: str | None
    retried_by_job_id: str | None
    recovery_action: str | None = None
    recovery_message: str | None = None
    can_retry: bool = False
    stages: list[JobRunStageView]


class AssetView(OrmView):
    id: str
    project_id: str
    kind: str
    role: str
    path: str
    content_hash: str
    mime_type: str
    width: int | None
    height: int | None
    duration: float | None
    fps: float | None
    sample_rate: int | None
    parent_asset_ids: list[str]
    scene_id: str | None
    shot_id: str | None
    provider: str
    workflow_run_id: str | None
    approval_state: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    created_at: datetime


class ConversationCreate(BaseModel):
    title: str = Field(default="Conversation", min_length=1, max_length=300)


class ConversationView(OrmView):
    id: str
    project_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: str = Field(min_length=1, max_length=100_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageView(OrmView):
    id: str
    conversation_id: str
    role: str
    content: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    created_at: datetime


class ActionPlanView(OrmView):
    id: str
    project_id: str
    conversation_id: str | None
    workflow_definition_id: str
    request_text: str
    provider: str
    inputs: dict[str, Any]
    expected_output: dict[str, Any]
    estimated_cost: float | None
    state: str
    job_id: str | None
    created_at: datetime
    updated_at: datetime


class ActionPlanTransitionView(OrmView):
    id: str
    action_plan_id: str
    from_state: str | None
    to_state: str
    reason: str
    created_at: datetime


class TimelineCreate(BaseModel):
    project_id: str
    scene_id: str | None = None
    name: str = Field(min_length=1, max_length=300)


class TimelineView(OrmView):
    id: str
    project_id: str
    scene_id: str | None
    name: str
    created_at: datetime
    updated_at: datetime


class TimelineVersionCreate(BaseModel):
    tracks: list[dict[str, Any]]
    state: Literal["draft", "proposed", "accepted", "rejected"] = "draft"
    edit_summary: str = Field(default="", max_length=20_000)


class TimelineRenderRequest(BaseModel):
    version_id: str
    approved: bool = False


class MediaAnalysisRequest(BaseModel):
    silence_noise_db: float = Field(default=-35.0, ge=-120, le=0)
    silence_duration: float = Field(default=0.5, gt=0, le=3600)
    black_pixel_threshold: float = Field(default=0.10, ge=0, le=1)
    black_duration: float = Field(default=0.5, gt=0, le=3600)
    freeze_noise_db: float = Field(default=-60.0, ge=-120, le=0)
    freeze_duration: float = Field(default=1.0, gt=0, le=3600)
    scene_threshold: float = Field(default=0.4, gt=0, le=1)


class MediaAnalysisView(BaseModel):
    asset_id: str
    facts: dict[str, Any]


class DerivativeBatchView(BaseModel):
    source_asset_id: str
    derivatives: list[AssetView]
    warnings: list[str] = Field(default_factory=list)


class WebcamCaptureView(BaseModel):
    asset: AssetView
    derivatives: list[AssetView]
    warnings: list[str] = Field(default_factory=list)


class ConversationPlanRequest(BaseModel):
    request_text: str = Field(min_length=1, max_length=20_000)


class AssistantReplyRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=100)


class ConversationPlanView(BaseModel):
    conversation_id: str
    result: dict[str, Any]
    message: MessageView


class HealthComponentView(BaseModel):
    ready: bool
    configured: bool | None = None
    optional: bool | None = None
    detail: str | None = None


class HealthView(BaseModel):
    status: str
    components: dict[str, HealthComponentView]


class WorkflowInputView(BaseModel):
    key: str
    type: Literal["string", "integer", "number", "boolean", "json", "asset:image", "asset:video"]
    required: bool
    description: str
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None


class WorkflowOutputView(BaseModel):
    kind: Literal["image", "video", "audio"]
    count: int


class WorkflowView(BaseModel):
    id: str
    name: str
    version: str
    capability: str
    execution_provider: Literal["local-comfyui", "bfl"]
    workflow_reference: str
    required_inputs: list[WorkflowInputView]
    output: WorkflowOutputView
    estimated_vram_gb: float | None
    estimated_cost: float | None
    requires_approval: bool
    enabled: bool


class GenerationProvenanceView(BaseModel):
    id: str
    job_id: str
    workflow_definition_id: str
    prompt: str
    negative_prompt: str
    seed: int | None
    model: str | None
    parameters: dict[str, Any]
    source_asset_ids: list[str]
    provider_response_metadata: dict[str, Any]
    created_at: datetime


class ImportProvenanceView(BaseModel):
    original_filename: str | None
    content_hash: str


class AssetProvenanceView(BaseModel):
    asset: AssetView
    generation: GenerationProvenanceView | None = None
    import_record: ImportProvenanceView | None = Field(default=None, alias="import")

    edit_summary: str = Field(default="", max_length=20_000)


class TimelineProposal(BaseModel):
    scene_id: str | None = None


class TimelineVersionView(OrmView):
    id: str
    timeline_id: str
    version_number: int
    state: str
    tracks: list[dict[str, Any]]
    edit_summary: str
    created_by: str
    created_at: datetime


class ProjectEventView(OrmView):
    id: str
    project_id: str
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    created_at: datetime
