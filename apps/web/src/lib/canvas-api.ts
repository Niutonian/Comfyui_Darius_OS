import { request, ApiError } from "./api-client";
import { loadCanvasIntent, saveCanvasIntent } from "./canvas-intent";
import { requestBoardSetup } from "./board-setup";
import type { CanvasContent } from "./canvas-document";
export type CanvasGeneration = { id: string; revision: number; jobId: string; seed: number | string; status: string; statusMessage: string; error: string | null; assetIds: string[]; provenance: Record<string, unknown>; createdAt: string; launchError?: string };
export type CanvasDocument = { id: string; projectId: string; revision: number; content: CanvasContent; activeGenerationId: string | null; updatedAt: string; generations: CanvasGeneration[] };
export type CanvasSummary = { id: string; name: string; revision: number; updatedAt: string };
export type CanvasEngine = { adapterVersion: string; presets: { id: string; name: string; width: number; height: number }[]; readiness?: { ready: boolean; issues: string[]; note?: string } };
const root = (project: string) => `/projects/${encodeURIComponent(project)}/canvases`;
const path = (project: string, id: string) => `${root(project)}/${encodeURIComponent(id)}`;
// Only definitive rejections may discard the saved transport identity.
export function definitiveGenerationError(error: unknown): boolean {
  return error instanceof ApiError && [400, 401, 403, 404, 409, 413, 422].includes(error.status);
}

async function submitGeneration<T>(path: string, body: string): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      request<T>(path, { method: "POST", body, signal: controller.signal }),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          reject(new ApiError("The queue acknowledgement timed out.", 408));
          controller.abort();
        }, 45_000);
      }),
    ]);
  } finally { clearTimeout(timer); }
}
export const canvasApi = {
  engine: (check = false, profile = "moss-bboxes-v1") => request<CanvasEngine>(`/canvas/engine?check=${check}&profile=${encodeURIComponent(profile)}`),
  example: (profile = "moss-bboxes-v1") => request<{ content: CanvasContent; warnings: string[] }>(`/canvas/example?profile=${encodeURIComponent(profile)}`),
  list: (project: string) => request<CanvasSummary[]>(root(project)),
  get: (project: string, id: string) => request<CanvasDocument>(path(project, id)),
  create: (project: string, content: CanvasContent) => request<CanvasDocument>(root(project), { method: "POST", body: JSON.stringify(content) }),
  save: (project: string, id: string, revision: number, content: CanvasContent) => request<CanvasDocument>(`${path(project, id)}/save`, { method: "POST", body: JSON.stringify({ revision, content }) }),
  generate: async (project: string, id: string, revision: number, idempotencyKey: string, seed: number | string | null, board?: { boardId: string; boardRevision: number; profileId?: string; promotedFromGenerationId?: string }, onChecking?: () => void) => {
    // Callers also pass saved intents/board context here. Only API fields may
    // leave this boundary; UI names, document IDs and retry keys are not inputs.
    const target = board ? { boardId: board.boardId, boardRevision: board.boardRevision,
      ...(board.profileId !== undefined ? { profileId: board.profileId } : {}),
      ...(board.promotedFromGenerationId !== undefined ? { promotedFromGenerationId: board.promotedFromGenerationId } : {}) } : {};
    const intentId = board?.promotedFromGenerationId ? `${id}:promote:${board.promotedFromGenerationId}` : id;
    const retry = loadCanvasIntent(project, intentId)?.key === idempotencyKey;
    saveCanvasIntent(project, intentId, { revision, key: idempotencyKey, seed, documentId: id, ...target });
    let setupCancelled = false;
    const lookup = () => request<CanvasGeneration | null>(`${path(project, id)}/requests/${encodeURIComponent(idempotencyKey)}`);
    try {
      if (retry) {
        onChecking?.();
        // If reconciliation is unavailable, keep the key and let the user retry.
        const existing = await lookup();
        if (existing) { saveCanvasIntent(project, intentId); return existing; }
      }
      const send = () => submitGeneration<CanvasGeneration>(`${path(project, id)}/generate`, JSON.stringify({ revision, idempotencyKey, seed, approved: true, ...target }));
      let result: CanvasGeneration;
      try { result = await send(); }
      catch (error) {
        if (!(error instanceof ApiError) || error.status !== 422 || !error.message.includes("Board setup required:")) throw error;
        try { await requestBoardSetup(board?.profileId ?? "moss-bboxes-v1"); }
        catch (error) { setupCancelled = true; throw error; }
        // Keep the exact saved revision, inputs, seed and idempotency key. Edits
        // made during setup cause the normal server revision check to stop it.
        result = await send();
      }
      saveCanvasIntent(project, intentId); return result;
    }
    catch (error) {
      if (setupCancelled) throw error;
      if (definitiveGenerationError(error)) { saveCanvasIntent(project, intentId); throw error; }
      onChecking?.();
      try {
        const existing = await lookup();
        if (existing) { saveCanvasIntent(project, intentId); return existing; }
      } catch { /* A failed read cannot establish whether submission committed. */ }
      throw new ApiError("Queue acknowledgement is uncertain. Your request is saved. Retry request will check for its job and reuse the same request; it will not create a fresh generation.", error instanceof ApiError ? error.status : 0);
    }
  },
  select: (project: string, id: string, generationId: string) => request<CanvasDocument>(`${path(project, id)}/select-result`, { method: "POST", body: JSON.stringify({ generationId }) }),
  start: (project: string, id: string, generationId: string) => request<CanvasGeneration>(`${path(project, id)}/generations/${generationId}/start`, { method: "POST" }),
};
