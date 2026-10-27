export type Project = {
  id: string;
  name: string;
  description: string;
  creative_brief: string;
  visual_style: string;
  default_aspect_ratio: string;
  default_resolution: string;
  default_fps: number;
  created_at: string;
  updated_at: string;
};

export type ProjectCreate = Pick<Project, "name"> & Partial<Pick<Project,
  | "description"
  | "creative_brief"
  | "visual_style"
  | "default_aspect_ratio"
  | "default_resolution"
  | "default_fps"
>>;

export type WorkflowInput = {
  key: string;
  type: "string" | "integer" | "number" | "boolean" | "json" | "asset:image" | "asset:video";
  required: boolean;
  description: string;
  default?: unknown;
  minimum?: number | null;
  maximum?: number | null;
};

export type Workflow = {
  registration?: { status: string; version?: number; source_digest?: string };
  assignable_purposes?: WorkflowPurpose[];
  input_hints?: { image?: boolean; video?: boolean };
  id: string;
  name: string;
  version: string;
  capability:
    | "text-to-image"
    | "image-to-image"
    | "text-to-video"
    | "image-to-video"
    | "video-to-video"
    | "character-sheet"
    | "face-consistency"
    | "lip-sync";
  execution_provider: "local-comfyui" | "bfl";
  workflow_reference: string;
  required_inputs: WorkflowInput[];
  output: { kind: "image" | "video" | "audio"; count: number };
  estimated_vram_gb: number | null;
  estimated_cost: number | null;
  requires_approval: boolean;
  enabled: boolean;
};

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | string;
export type WorkflowPurpose = Workflow["capability"] | "image-upscale";

export type RecipeManifest = {
  contract_digest?: string;
  workflow_id: string;
  version: number;
  status: "ready" | "needs_mapping";
  graph_digest: string;
  source_digest: string;
  scene_slots: string[];
  protected_slots: string[];
  unresolved_slots: string[];
  processing_only: boolean;
  fields: { slot: string; label: string; value: string; role: "scene" | "system" | "negative" | "preserve" | "unresolved"; editable?: boolean }[];
};

export type BlockPartyReadiness = {
  ready: boolean;
  issues: { code: string; message: string }[];
  warnings: string[];
  checked: { models: number; node_packs: number; node_classes: number };
  checked_at: string;
  note: string;
};

export type BlockPartyImportResult = {
  workflow_id: string;
  name: string;
  already_imported: boolean;
  registration: RecipeManifest;
  output_kind: "image" | "video";
  note: string;
};
export type TrustedWorkflowPreferences = {
  enabled: boolean;
  entries: { workflow_id: string; purpose: WorkflowPurpose; is_default: boolean }[];
  unavailable_ids?: string[];
  global_defaults?: { enabled: boolean; entries: TrustedWorkflowPreferences["entries"] };
};

export type Job = {
  display_name?: string; indeterminate_progress?: boolean; canvas_board_id?: string | null;
  id: string;
  project_id: string;
  job_type: string;
  provider: string;
  status: JobStatus;
  progress: number;
  status_message: string;
  output_asset_ids: string[];
  external_job_id: string | null;
  error_code: string | null;
  error_detail: string | null;
  attempt_count: number;
  retry_of_job_id: string | null;
  cancellation_requested: boolean;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type JobRunStage = {
  key: string;
  label: string;
  state: "pending" | "current" | "completed" | "failed" | "cancelled";
  detail: string;
  occurred_at: string | null;
};

export type JobRun = {
  job_id: string;
  workflow_id: string | null;
  request_text: string | null;
  retry_of_job_id: string | null;
  retried_by_job_id: string | null;
  recovery_action: string | null;
  recovery_message: string | null;
  can_retry: boolean;
  stages: JobRunStage[];
};

export type GenerationRequest = {
  workflow_id: string;
  request_text: string;
  inputs: Record<string, unknown>;
  approved: boolean;
};

export type Asset = {
  id: string;
  project_id: string;
  kind: string;
  role: string;
  path: string;
  content_hash: string;
  mime_type: string;
  width: number | null;
  height: number | null;
  duration: number | null;
  fps: number | null;
  sample_rate: number | null;
  parent_asset_ids: string[];
  scene_id: string | null;
  shot_id: string | null;
  provider: string;
  workflow_run_id: string | null;
  approval_state: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type Provenance = {
  asset: Asset;
  generation: {
    id: string;
    job_id: string;
    workflow_definition_id: string;
    prompt: string;
    negative_prompt: string;
    seed: number | null;
    model: string | null;
    parameters: Record<string, unknown>;
    source_asset_ids: string[];
    provider_response_metadata: Record<string, unknown>;
    created_at: string;
  } | null;
  import?: {
    original_filename: string | null;
    content_hash: string;
  };
};

export type Health = {
  status: string;
  components: Record<string, { ready: boolean; configured?: boolean; optional?: boolean; detail?: string }>;
};

export type LlmProviderId = "openai" | "deepseek" | "ollama" | "llamacpp" | "opencode";

export type LlmProviderOption = {
  id: LlmProviderId;
  label: string;
  models: string[];
  credential_configured: boolean;
  model_capabilities?: Record<string, { vision?: boolean; tools?: boolean }>;
  reasoning_efforts?: Record<string, string[]>;
};

export type LlmSettings = {
  provider: LlmProviderId;
  model: string;
  reasoning_effort?: string;
  ready: boolean;
  credential_configured: boolean;
  source: "environment" | "saved";
  providers: LlmProviderOption[];
};

export type Selection =
  | { type: "character"; id: string }
  | { type: "scene"; id: string }
  | { type: "project"; id: string }
  | { type: "workflow"; id: string }
  | { type: "job"; id: string }
  | { type: "asset"; id: string }
  | null;

export type ViewId = "home" | "talk" | "create" | "map" | "edit" | "settings";

export type ThemeMode = "light" | "dark";

export type DariusMood = "idle" | "thinking" | "listening" | "speaking";

export type MapAltitude = "world" | "cast" | "places" | "media" | "tools";


export type ProjectDetail = Project & {
  character_count: number;
  scene_count: number;
  asset_count: number;
};

export type CharacterCreate = {
  name: string;
  description?: string;
  canonical_prompt?: string;
  negative_prompt?: string;
  continuity_notes?: string;
  voice_profile_id?: string | null;
  metadata?: Record<string, unknown>;
  approved_reference_asset_ids?: string[];
};

export type Character = Required<Omit<CharacterCreate, "voice_profile_id">> & {
  id: string;
  project_id: string;
  voice_profile_id: string | null;
  created_at: string;
  updated_at: string;
};

export type SceneCreate = {
  number: number;
  title: string;
  description?: string;
  screenplay_text?: string;
  location?: string;
  time_of_day?: string;
  mood?: string;
  status?: "draft" | "planned" | "ready" | "complete";
};

export type Scene = Required<SceneCreate> & {
  id: string;
  project_id: string;
  created_at: string;
  updated_at: string;
};

export type ShotCreate = {
  number: number;
  description?: string;
  shot_type?: string;
  camera_motion?: string;
  duration_target?: number;
  dialogue?: string;
  status?: "planned" | "ready" | "generated" | "selected" | "complete";
  selected_asset_id?: string | null;
};

export type Shot = Required<Omit<ShotCreate, "selected_asset_id">> & {
  id: string;
  scene_id: string;
  selected_asset_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ShotBoardEntry = { shot: Shot; scene_title: string; scene_number: number; references: Asset[]; takes: Asset[]; jobs: Array<{ id: string; status: string; progress: number; status_message: string }> };
export type ShotProductionUpdate = { reference_asset_ids?: string[]; take_asset_ids?: string[]; selected_asset_id?: string | null; status?: Shot["status"] };
export type AssistantContext = { notes: string; character_id: string | null; scene_id: string | null; shot_id: string | null; reference_asset_ids: string[] };

export type Conversation = {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type WorkflowProposal = {
  project_id: string;
  request_text: string;
  inputs: Record<string, unknown>;
  conversation_id?: string | null;
  source_message_id?: string | null;
};

export type RenderPreview = {
  canvases?: { node_id: string; width: number; height: number }[];
  workflow_id: string;
  workflow_name: string;
  origin_workflow_id: string | null;
  provider: string;
  verification: "graph" | "contract";
  graph_digest: string | null;
  positive: Array<{ slot: string; label: string; value: string }>;
  negative: Array<{ slot: string; label: string; value: string }>;
  models: Array<{ slot: string; label: string; value: string }>;
  image_inputs: Array<{ slot: string; label: string; value: string }>;
  reference_asset_ids: string[];
  warnings: string[];
  blocked: boolean;
};

export type ActionPlan = {
  id: string;
  project_id: string;
  conversation_id: string | null;
  workflow_definition_id: string;
  request_text: string;
  provider: string;
  inputs: Record<string, unknown>;
  expected_output: { kind: "image" | "video" | "audio"; count: number; render_preview?: RenderPreview };
  estimated_cost: number | null;
  state: string;
  job_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ActionPlanTransition = {
  id: string;
  action_plan_id: string;
  from_state: string | null;
  to_state: string;
  reason: string;
  created_at: string;
};

export type Timeline = {
  id: string;
  project_id: string;
  scene_id: string | null;
  name: string;
  created_at: string;
  updated_at: string;
};

export type TimelineVersion = {
  id: string;
  timeline_id: string;
  version_number: number;
  state: string;
  tracks: Array<Record<string, unknown>>;
  edit_summary: string;
  created_by: string;
  created_at: string;
};

export type ProjectEvent = {
  id: string;
  project_id: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type TimelineClip = {
  id: string;
  source_asset_id?: string;
  shot_id?: string;
  text?: string;
  source_in?: number;
  source_out?: number;
  timeline_in: number;
  timeline_out: number;
  reason?: string;
  confidence?: number;
  muted?: boolean;
  volume?: number;
  fade_in?: number;
  fade_out?: number;
  audio_start?: number;
  audio_end?: number;
};

export type TimelineTrack = {
  kind: "video" | "audio" | "dialogue" | string;
  clips: TimelineClip[];
};

export type UploadProgress = {
  loaded: number;
  total: number;
  percent: number;
};


export type DerivativeBatch = {
  source_asset_id: string;
  derivatives: Asset[];
  warnings: string[];
};

export type WebcamCapture = {
  asset: Asset;
  derivatives: Asset[];
  warnings: string[];
};

export type MediaAnalysisRequest = {
  silence_noise_db?: number;
  silence_duration?: number;
  black_pixel_threshold?: number;
  black_duration?: number;
  freeze_noise_db?: number;
  freeze_duration?: number;
  scene_threshold?: number;
};

export type MediaAnalysis = {
  asset_id: string;
  facts: Record<string, unknown>;
};

export type ConversationPlan = {
  conversation_id: string;
  result: Record<string, unknown>;
  message: Message;
};

export type OtioDocument = Record<string, unknown>;
