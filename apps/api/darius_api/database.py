from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    creative_brief: Mapped[str] = mapped_column(Text, default="", nullable=False)
    visual_style: Mapped[str] = mapped_column(Text, default="", nullable=False)
    default_aspect_ratio: Mapped[str] = mapped_column(String(30), default="16:9", nullable=False)
    default_resolution: Mapped[str] = mapped_column(String(30), default="1920x1080", nullable=False)
    default_fps: Mapped[float] = mapped_column(Float, default=24.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ShotProduction(Base):
    __tablename__ = "shot_production"
    shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id"), primary_key=True)
    links_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class LocalRenderPermission(Base):
    __tablename__ = "local_render_permissions"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class LlmPreference(Base):
    __tablename__ = "llm_preferences"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="default")
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    reasoning_effort: Mapped[str] = mapped_column(String(20), default="auto", server_default="auto", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class GlobalWorkflowPreference(Base):
    __tablename__ = "global_workflow_preferences"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="default")
    preferences_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Character(Base):
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_character_project_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    canonical_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    continuity_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    voice_profile_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_scene_project_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    screenplay_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    location: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    time_of_day: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    mood: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Shot(Base):
    __tablename__ = "shots"
    __table_args__ = (UniqueConstraint("scene_id", "number", name="uq_shot_scene_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id"), index=True, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    shot_type: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    camera_motion: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    duration_target: Mapped[float] = mapped_column(Float, default=3.0, nullable=False)
    dialogue: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="planned", nullable=False)
    selected_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WorkflowDefinitionRecord(Base):
    __tablename__ = "workflow_definitions"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    capability: Mapped[str] = mapped_column(String(50), nullable=False)
    execution_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    contract: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    @property
    def display_name(self):
        from .chat_labels import job_label
        return job_label(self)

    @property
    def indeterminate_progress(self):
        return bool((self.input_payload or {}).get("canvas_generation_id"))

    @property
    def canvas_board_id(self):
        return (self.input_payload or {}).get("canvas_board_id")

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    job_type: Mapped[str] = mapped_column(String(50), default="generation", nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), index=True, default="queued", nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status_message: Mapped[str] = mapped_column(Text, default="Queued", nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    external_job_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_of_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CanvasSeed(TypeDecorator):
    """Lossless uint64 storage while retaining integer semantics in Python."""
    impl = String(20)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return str(value) if value is not None else None

    def process_result_value(self, value, dialect):
        return int(value) if value is not None else None


class GenerationRecord(Base):
    __tablename__ = "generation_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True, nullable=False)
    workflow_definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    seed: Mapped[int | None] = mapped_column(CanvasSeed(), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    provider_response_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(30), index=True, default="generation", nullable=False)
    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id"), index=True, nullable=True)
    shot_id: Mapped[str | None] = mapped_column(ForeignKey("shots.id"), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    approval_state: Mapped[str] = mapped_column(String(30), index=True, default="pending", nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CharacterAssetReference(Base):
    __tablename__ = "character_asset_references"

    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AssistantMemory(Base):
    __tablename__ = "assistant_memory"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="Conversation", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ActionPlan(Base):
    __tablename__ = "action_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    workflow_definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"), nullable=False)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    expected_output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String(30), index=True, default="proposed", nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ActionPlanTransition(Base):
    __tablename__ = "action_plan_transitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_plan_id: Mapped[str] = mapped_column(ForeignKey("action_plans.id"), index=True, nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Timeline(Base):
    __tablename__ = "timelines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TimelineVersion(Base):
    __tablename__ = "timeline_versions"
    __table_args__ = (UniqueConstraint("timeline_id", "version_number", name="uq_timeline_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    timeline_id: Mapped[str] = mapped_column(ForeignKey("timelines.id"), index=True, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(30), default="proposed", nullable=False)
    tracks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    edit_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str] = mapped_column(String(30), default="darius", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProjectEvent(Base):
    __tablename__ = "project_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CanvasDocumentRecord(Base):
    __tablename__ = "canvas_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active_generation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    selection_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CanvasRevisionRecord(Base):
    __tablename__ = "canvas_revisions"
    document_id: Mapped[str] = mapped_column(ForeignKey("canvas_documents.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CanvasGenerationRecord(Base):
    __tablename__ = "canvas_generations"
    __table_args__ = (UniqueConstraint("document_id", "idempotency_key", name="uq_canvas_request"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("canvas_documents.id"), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    seed: Mapped[int] = mapped_column(CanvasSeed(), nullable=False)
    selection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CanvasWorkspaceRecord(Base):
    __tablename__ = "canvas_workspaces"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    placements_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)


class MossBoardRecord(Base):
    __tablename__ = "moss_boards"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("canvas_documents.id"), unique=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
