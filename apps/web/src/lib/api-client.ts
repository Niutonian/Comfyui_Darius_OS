import { readReplyStream } from "./reply-stream";
import type { TrustedWorkflowPreferences } from "./types";
import type { RecipeManifest } from "./types";
import type { BlockPartyImportResult, BlockPartyReadiness } from "./types";
import type { RenderPreview, ShotBoardEntry, ShotProductionUpdate } from "./types";
import type {
  ActionPlan,
  AssistantContext,
  ActionPlanTransition,
  Asset,
  Character,
  CharacterCreate,
  Conversation,
  ConversationPlan,
  DerivativeBatch,
  GenerationRequest,
  Health,
  Job,
  JobRun,
  LlmProviderId,
  LlmSettings,
  LlmProviderOption,
  MediaAnalysis,
  MediaAnalysisRequest,
  Message,
  OtioDocument,
  Project,
  ProjectCreate,
  ProjectDetail,
  ProjectEvent,
  Provenance,
  Scene,
  SceneCreate,
  Shot,
  ShotCreate,
  Timeline,
  TimelineVersion,
  UploadProgress,
  WebcamCapture,
  Workflow,
  WorkflowProposal,
} from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_DARIUS_API_BASE_URL ?? "/api/darius/api/v1").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function formatApiError(value: unknown, fallback: string, depth = 0): string {
  if (depth > 4) return fallback;
  if (typeof value === "string") return value.trim() || fallback;
  if (Array.isArray(value)) {
    const messages = value.slice(0, 8).map(item => formatApiError(item, "", depth + 1)).filter(Boolean);
    if (!messages.length) return fallback;
    return messages.join("; ") + (value.length > 8 ? `; ${value.length - 8} more issues` : "");
  }
  if (value && typeof value === "object") {
    const error = value as Record<string, unknown>;
    if (typeof error.msg === "string" && Array.isArray(error.loc)) {
      const parts = error.loc.filter(part => typeof part === "string" || typeof part === "number");
      if (["body", "query", "path"].includes(String(parts[0]))) parts.shift();
      return (parts.length ? parts.join(".") + ": " : "") + error.msg;
    }
    for (const key of ["detail", "message", "msg", "error", "errors"]) {
      if (error[key] !== undefined) {
        const message = formatApiError(error[key], "", depth + 1);
        if (message) return message;
      }
    }
  }
  // Validation input/ctx may contain user data. Never stringify the whole body.
  return fallback;
}

export async function request<T>(path: string, init?: RequestInit, readDeadlineMs = 20_000): Promise<T> {
  // Bound discovery/read requests; mutations and conversations manage their own lifecycle.
  if (init?.signal || (init?.method && init.method.toUpperCase() !== "GET")) return performRequest<T>(path, init);
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      performRequest<T>(path, { ...init, signal: controller.signal }),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          const chatRead = /\/(conversations|messages)(?:\?|$)/.test(path);
          reject(new ApiError(chatRead
            ? "Loading the conversation took too long. Your messages are still saved. Reload the conversation to reconnect."
            : "The local Darius API did not respond within 20 seconds. Check that it is running, then retry.", 408));
          controller.abort();
        }, readDeadlineMs);
      }),
    ]);
  } finally { clearTimeout(timer); }
}

async function performRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: isFormData ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (error) {
    throw new ApiError(
      "Darius is offline. Start the local API and try again.",
      0,
      error instanceof Error ? error.message : undefined,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = formatApiError(await response.json(), detail);
    } catch {
      // Keep the HTTP status text when the body is not JSON.
    }
    throw new ApiError(detail || "The Darius API rejected the request.", response.status, detail);
  }

  return (await response.json()) as T;
}

async function conversationRequest<T>(path: string, init: RequestInit, timeoutMs = 20_000): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      request<T>(path, { ...init, signal: controller.signal }),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          reject(new ApiError("Darius did not reply in time. Your message is kept here. Please retry the reply.", 408));
          controller.abort();
        }, timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

function uploadWithProgress<T>(
  path: string,
  file: File,
  fields: Record<string, string | undefined>,
  options: { onProgress?: (progress: UploadProgress) => void; signal?: AbortSignal } = {},
): Promise<T> {
  const form = new FormData();
  form.set("file", file);
  Object.entries(fields).forEach(([key, value]) => {
    if (value !== undefined) form.set(key, value);
  });

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    xhr.open("POST", `${API_BASE}${path}`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => {
      const total = event.lengthComputable ? event.total : file.size;
      const percent = total > 0 ? Math.min(100, Math.round((event.loaded / total) * 100)) : 0;
      options.onProgress?.({ loaded: event.loaded, total, percent });
    };
    xhr.onload = () => {
      options.signal?.removeEventListener("abort", abort);
      const body = xhr.response as T | { detail?: unknown } | null;
      if (xhr.status >= 200 && xhr.status < 300 && body) {
        options.onProgress?.({ loaded: file.size, total: file.size, percent: 100 });
        resolve(body as T);
        return;
      }
      const detail = formatApiError(body, xhr.statusText || "The Darius API rejected the upload.");
      reject(new ApiError(detail || "The Darius API rejected the upload.", xhr.status, detail));
    };
    xhr.onerror = () => reject(new ApiError("Darius is offline. The media could not be uploaded.", 0));
    xhr.onabort = () => reject(new ApiError("Upload cancelled.", 0));
    options.signal?.addEventListener("abort", abort, { once: true });
    if (options.signal?.aborted) abort();
    else xhr.send(form);
  });
}

function uploadAssetWithProgress(
  file: File,
  fields: { project_id: string; role?: "source" | "reference"; scene_id?: string; shot_id?: string; approval_state?: "pending" | "approved" | "rejected" },
  options: { onProgress?: (progress: UploadProgress) => void; signal?: AbortSignal } = {},
): Promise<Asset> {
  return uploadWithProgress<Asset>("/assets/upload", file, fields, options);
}


function withQuery(path: string, values: Record<string, string | number | null | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export const api = {
  registerRecipe: (workflowId: string, force = false) => request<RecipeManifest>("/workflow-recipes/register", { method: "POST", body: JSON.stringify({ workflow_id: workflowId, force }), signal: AbortSignal.timeout(150_000) }),
  importBlockParty: (file: File) => {
    const body = new FormData(); body.append("file", file);
    return request<BlockPartyImportResult>("/workflow-recipes/block-party/import", { method: "POST", body, signal: AbortSignal.timeout(60_000) });
  },
  blockPartyReadiness: (workflowId: string) => request<BlockPartyReadiness>("/workflow-recipes/block-party/readiness", { method: "POST", body: JSON.stringify({ workflow_id: workflowId }), signal: AbortSignal.timeout(300_000) }),
  saveRecipeMapping: (workflowId: string, sourceDigest: string, roles: Record<string, string>) => request<RecipeManifest>("/workflow-recipes/registration", { method: "PUT", body: JSON.stringify({ workflow_id: workflowId, source_digest: sourceDigest, roles }) }),
  workflowRecipes: () => request<{ workflows: Workflow[]; folder: string; note: string }>("/workflow-recipes"),
  globalWorkflowDefaults: () => request<TrustedWorkflowPreferences>("/settings/workflow-defaults"),
  saveGlobalWorkflowDefaults: (value: TrustedWorkflowPreferences) => request<TrustedWorkflowPreferences>("/settings/workflow-defaults", { method: "PUT", body: JSON.stringify({ enabled: value.enabled, entries: value.entries }) }),
  refreshWorkflowRecipes: () => request<{ workflows: Workflow[]; folder: string; note: string }>("/workflow-recipes/refresh", { method: "POST", signal: AbortSignal.timeout(30_000) }),
  workflowInputOptions: (id: string) => request<Record<string, Array<string | number | boolean>>>(`/workflows/${encodeURIComponent(id)}/input-options`),
  previewWorkflow: (id: string, payload: WorkflowProposal) => request<RenderPreview>(`/workflows/${encodeURIComponent(id)}/preview`, { method: "POST", body: JSON.stringify(payload), signal: AbortSignal.timeout(10000) }),
  llmSettings: () => request<LlmSettings>("/settings/llm"),
  refreshLlmModels: (provider: "openai" | "opencode" | "ollama") => request<LlmProviderOption>(`/settings/llm/${provider}/models/refresh`, { method: "POST", signal: AbortSignal.timeout(60_000) }),
  setLlmSettings: (provider: LlmProviderId, model: string, reasoningEffort?: string) =>
    request<LlmSettings>("/settings/llm", { method: "POST", body: JSON.stringify({ provider, model, ...(reasoningEffort === undefined ? {} : { reasoning_effort: reasoningEffort }) }) }),
  localRendering: (projectId: string) => request<{ enabled: boolean }>(`/projects/${projectId}/local-rendering`),
  setLocalRendering: (projectId: string, enabled: boolean) => request<{ enabled: boolean }>(`/projects/${projectId}/local-rendering`, { method: "POST", body: JSON.stringify({ enabled }) }),
  health: () => request<Health>("/health"),
  projects: () => request<Project[]>("/projects"),
  project: (projectId: string) => request<ProjectDetail>(`/projects/${encodeURIComponent(projectId)}`),
  createProject: (payload: ProjectCreate) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (projectId: string, payload: { name?: string; description?: string }) =>
    request<Project>(`/projects/${encodeURIComponent(projectId)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteProject: (projectId: string) => request<void>(`/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" }),
  characters: (projectId: string) => request<Character[]>(`/projects/${encodeURIComponent(projectId)}/characters`),
  createCharacter: (projectId: string, payload: CharacterCreate) =>
    request<Character>(`/projects/${encodeURIComponent(projectId)}/characters`, { method: "POST", body: JSON.stringify(payload) }),
  updateCharacter: (projectId: string, id: string, payload: CharacterCreate) =>
    request<Character>(`/projects/${encodeURIComponent(projectId)}/characters/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  scenes: (projectId: string) => request<Scene[]>(`/projects/${encodeURIComponent(projectId)}/scenes`),
  createScene: (projectId: string, payload: SceneCreate) =>
    request<Scene>(`/projects/${encodeURIComponent(projectId)}/scenes`, { method: "POST", body: JSON.stringify(payload) }),
  updateScene: (projectId: string, id: string, payload: SceneCreate) =>
    request<Scene>(`/projects/${encodeURIComponent(projectId)}/scenes/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  shots: (sceneId: string) => request<Shot[]>(`/scenes/${encodeURIComponent(sceneId)}/shots`),
  createShot: (sceneId: string, payload: ShotCreate) =>
    request<Shot>(`/scenes/${encodeURIComponent(sceneId)}/shots`, { method: "POST", body: JSON.stringify(payload) }),
  updateShot: (sceneId: string, id: string, payload: ShotCreate) =>
    request<Shot>(`/scenes/${encodeURIComponent(sceneId)}/shots/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  workflows: (projectId?: string | null) => request<Workflow[]>(withQuery("/workflows", { project_id: projectId })),
  trustedWorkflows: (projectId: string) => request<TrustedWorkflowPreferences>(`/projects/${encodeURIComponent(projectId)}/trusted-workflows`),
  saveTrustedWorkflows: (projectId: string, value: TrustedWorkflowPreferences) => request<TrustedWorkflowPreferences>(`/projects/${encodeURIComponent(projectId)}/trusted-workflows`, { method: "PUT", body: JSON.stringify({ enabled: value.enabled, entries: value.entries }) }),
  bflConnection: () => request<{ configured: boolean; authenticated: boolean; credits_available: boolean }>("/bfl/connection"),
  assistantContext: (projectId: string) => request<AssistantContext>(`/projects/${encodeURIComponent(projectId)}/assistant-context`),
  shotBoard: (projectId: string) => request<ShotBoardEntry[]>(`/projects/${encodeURIComponent(projectId)}/shot-board`),
  updateShotProduction: (projectId: string, shotId: string, payload: ShotProductionUpdate) => request<Shot>(`/projects/${encodeURIComponent(projectId)}/shot-board/${encodeURIComponent(shotId)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  saveAssistantContext: (projectId: string, context: AssistantContext) => request<AssistantContext>(`/projects/${encodeURIComponent(projectId)}/assistant-context`, { method: "PUT", body: JSON.stringify(context) }),
  projectWorkflows: (projectId: string) => request<Workflow[]>(`/projects/${encodeURIComponent(projectId)}/workflows`),
  proposeWorkflow: (workflowId: string, payload: WorkflowProposal) =>
    request<ActionPlan>(`/workflows/${encodeURIComponent(workflowId)}/propose`, { method: "POST", body: JSON.stringify(payload) }),
  createRequest: (projectId: string, payload: GenerationRequest) =>
    request<Job>(`/projects/${encodeURIComponent(projectId)}/requests`, { method: "POST", body: JSON.stringify(payload) }),
  actionPlan: (planId: string) => request<ActionPlan>(`/action-plans/${encodeURIComponent(planId)}`),
  actionPlanTransitions: (planId: string) => request<ActionPlanTransition[]>(`/action-plans/${encodeURIComponent(planId)}/transitions`),
  approveActionPlan: (planId: string) => request<ActionPlan>(`/action-plans/${encodeURIComponent(planId)}/approve`, { method: "POST" }),
  cancelActionPlan: (planId: string) => request<ActionPlan>(`/action-plans/${encodeURIComponent(planId)}/cancel`, { method: "POST" }),
  jobs: (filters: { project_id?: string; status?: string } = {}) => request<Job[]>(withQuery("/jobs", filters)),
  job: (jobId: string) => request<Job>(`/jobs/${encodeURIComponent(jobId)}`),
  jobRun: (jobId: string) => request<JobRun>(`/jobs/${encodeURIComponent(jobId)}/run`),
  cancelJob: (jobId: string) => request<Job>(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  startRenderJob: (jobId: string) => request<Job>(`/jobs/${encodeURIComponent(jobId)}/start-render`, { method: "POST" }),
  retryJob: (jobId: string) => request<Job>(`/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" }),
  assets: (filters: { project_id?: string; kind?: string; role?: string; provider?: string; approval_state?: string; scene_id?: string; shot_id?: string; q?: string; limit?: number } = {}) =>
    request<Asset[]>(withQuery("/assets", filters)),
  asset: (assetId: string) => request<Asset>(`/assets/${encodeURIComponent(assetId)}`),
  deleteAsset: (assetId: string) => request<void>(`/assets/${encodeURIComponent(assetId)}`, { method: "DELETE" }),
  assetContentUrl: (assetId: string) => `${API_BASE}/assets/${encodeURIComponent(assetId)}/content`,
  provenance: (assetId: string) => request<Provenance>(`/assets/${encodeURIComponent(assetId)}/provenance`),
  uploadAsset: (file: File, fields: { project_id: string; role?: "source" | "reference"; scene_id?: string; shot_id?: string; approval_state?: "pending" | "approved" | "rejected" }) =>
    uploadAssetWithProgress(file, fields),
  uploadAssetWithProgress: (
    file: File,
    fields: { project_id: string; role?: "source" | "reference"; scene_id?: string; shot_id?: string; approval_state?: "pending" | "approved" | "rejected" },
    options: { onProgress?: (progress: UploadProgress) => void; signal?: AbortSignal } = {},
  ) => uploadAssetWithProgress(file, fields, options),
  captureWebcamWithProgress: (
    file: File,
    fields: { project_id: string; scene_id?: string; shot_id?: string },
    options: { onProgress?: (progress: UploadProgress) => void; signal?: AbortSignal } = {},
  ) => uploadWithProgress<WebcamCapture>("/assets/webcam-capture", file, fields, options),
  createDerivatives: (assetId: string) =>
    request<DerivativeBatch>(`/assets/${encodeURIComponent(assetId)}/derivatives`, { method: "POST" }),
  analyzeAsset: (assetId: string, payload: MediaAnalysisRequest = {}) =>
    request<MediaAnalysis>(`/assets/${encodeURIComponent(assetId)}/analyze`, { method: "POST", body: JSON.stringify(payload) }),
  conversations: (projectId: string) => request<Conversation[]>(`/projects/${encodeURIComponent(projectId)}/conversations`, undefined, 45_000),
  renameConversation: (projectId: string, conversationId: string, title: string) =>
    request<Conversation>(`/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(conversationId)}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  deleteConversation: (projectId: string, conversationId: string) =>
    request<{ deleted: string }>(`/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" }),
  createConversation: (projectId: string, title = "Conversation") =>
    conversationRequest<Conversation>(`/projects/${encodeURIComponent(projectId)}/conversations`, { method: "POST", body: JSON.stringify({ title }) }),
  messages: (conversationId: string) => request<Message[]>(`/conversations/${encodeURIComponent(conversationId)}/messages`, undefined, 45_000),
  createMessage: (conversationId: string, payload: Pick<Message, "role" | "content"> & { metadata?: Record<string, unknown> }) =>
    conversationRequest<Message>(`/conversations/${encodeURIComponent(conversationId)}/messages`, { method: "POST", body: JSON.stringify(payload) }),
  planConversation: (conversationId: string, requestText: string) =>
    request<ConversationPlan>(`/conversations/${encodeURIComponent(conversationId)}/plan`, { method: "POST", body: JSON.stringify({ request_text: requestText }) }),
  assistantReply: (conversationId: string, messageId: string) =>
    conversationRequest<Message>(`/conversations/${encodeURIComponent(conversationId)}/reply`, { method: "POST", body: JSON.stringify({ message_id: messageId }) }, 300_000),
  assistantReplyStream: async (conversationId: string, messageId: string, onDelta: (text: string) => void) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 300_000);
    try {
      const path = `/conversations/${encodeURIComponent(conversationId)}/reply`;
      const response = await fetch(`${API_BASE}${path}/stream`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message_id: messageId }), signal: controller.signal });
      if (response.status === 404 || response.status === 405) return conversationRequest<Message>(path, { method: "POST", body: JSON.stringify({ message_id: messageId }) }, 300_000);
      if (!response.ok) throw new ApiError(formatApiError(await response.json(), "Darius could not reply."), response.status);
      return await readReplyStream(response, onDelta);
    } catch (error) {
      if (controller.signal.aborted) throw new ApiError("The final reply was incomplete. Retry to resume the saved task.", 408);
      throw error;
    } finally { clearTimeout(timer); }
  },
  retryPreparation: (conversationId: string, messageId: string) => request<Message>(`/conversations/${conversationId}/messages/${messageId}/retry-preparation`, { method: "POST" }),
  controlTask: (conversationId: string, messageId: string, action: "pause" | "resume" | "cancel") =>
    request<Message>(`/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/task/${action}`, { method: "POST" }),
  projectEvents: (projectId: string, limit = 200) => request<ProjectEvent[]>(withQuery(`/projects/${encodeURIComponent(projectId)}/events`, { limit })),
  eventsStreamUrl: (projectId?: string) => `${API_BASE}${withQuery("/events/stream", { project_id: projectId })}`,
  timelines: (projectId?: string) => request<Timeline[]>(withQuery("/timelines", { project_id: projectId })),
  createTimeline: (payload: { project_id: string; scene_id?: string | null; name: string }) =>
    request<Timeline>("/timelines", { method: "POST", body: JSON.stringify(payload) }),
  timelineVersions: (timelineId: string) => request<TimelineVersion[]>(`/timelines/${encodeURIComponent(timelineId)}/versions`),
  audioPreview: (assetId: string, projectId: string) => request<{ has_audio: boolean; peaks: number[]; duration: number; partial: boolean }>(`/assets/${encodeURIComponent(assetId)}/audio-preview?project_id=${encodeURIComponent(projectId)}`),
  createTimelineVersion: (timelineId: string, payload: { tracks: Array<Record<string, unknown>>; state?: "draft" | "proposed" | "accepted" | "rejected"; edit_summary?: string }) =>
    request<TimelineVersion>(`/timelines/${encodeURIComponent(timelineId)}/versions`, { method: "POST", body: JSON.stringify(payload) }),
  timelineOtio: (timelineId: string, versionId: string) =>
    request<OtioDocument>(`/timelines/${encodeURIComponent(timelineId)}/versions/${encodeURIComponent(versionId)}/otio`),
  renderTimeline: (timelineId: string, versionId: string, approved: boolean) =>
    request<Job>(`/timelines/${encodeURIComponent(timelineId)}/render`, { method: "POST", body: JSON.stringify({ version_id: versionId, approved }) }),
  proposeTimeline: (timelineId: string, sceneId?: string | null) =>
    request<TimelineVersion>(`/timelines/${encodeURIComponent(timelineId)}/propose`, { method: "POST", body: JSON.stringify({ scene_id: sceneId ?? null }) }),
};
