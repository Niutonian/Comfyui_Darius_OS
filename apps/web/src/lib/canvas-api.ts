import { request, ApiError } from "./api-client";
import { saveCanvasIntent } from "./canvas-intent";
import { requestBoardSetup } from "./board-setup";
import type { CanvasContent } from "./canvas-document";
export type CanvasGeneration = { id: string; revision: number; jobId: string; seed: number | string; status: string; statusMessage: string; error: string | null; assetIds: string[]; provenance: Record<string, unknown>; createdAt: string; launchError?: string };
export type CanvasDocument = { id: string; projectId: string; revision: number; content: CanvasContent; activeGenerationId: string | null; updatedAt: string; generations: CanvasGeneration[] };
export type CanvasSummary = { id: string; name: string; revision: number; updatedAt: string };
export type CanvasEngine = { adapterVersion: string; presets: { id: string; name: string; width: number; height: number }[]; readiness?: { ready: boolean; issues: string[]; note?: string } };
const root = (project: string) => `/projects/${encodeURIComponent(project)}/canvases`;
const path = (project: string, id: string) => `${root(project)}/${encodeURIComponent(id)}`;
export const canvasApi = {
  engine: (check = false, profile = "moss-bboxes-v1") => request<CanvasEngine>(`/canvas/engine?check=${check}&profile=${encodeURIComponent(profile)}`),
  example: (profile = "moss-bboxes-v1") => request<{ content: CanvasContent; warnings: string[] }>(`/canvas/example?profile=${encodeURIComponent(profile)}`),
  list: (project: string) => request<CanvasSummary[]>(root(project)),
  get: (project: string, id: string) => request<CanvasDocument>(path(project, id)),
  create: (project: string, content: CanvasContent) => request<CanvasDocument>(root(project), { method: "POST", body: JSON.stringify(content) }),
  save: (project: string, id: string, revision: number, content: CanvasContent) => request<CanvasDocument>(`${path(project, id)}/save`, { method: "POST", body: JSON.stringify({ revision, content }) }),
  generate: async (project: string, id: string, revision: number, idempotencyKey: string, seed: number | string | null, board?: { boardId: string; boardRevision: number; profileId?: string; promotedFromGenerationId?: string }) => {
    // Callers also pass saved intents/board context here. Only API fields may
    // leave this boundary; UI names, document IDs and retry keys are not inputs.
    const target = board ? { boardId: board.boardId, boardRevision: board.boardRevision,
      ...(board.profileId !== undefined ? { profileId: board.profileId } : {}),
      ...(board.promotedFromGenerationId !== undefined ? { promotedFromGenerationId: board.promotedFromGenerationId } : {}) } : {};
    const intentId = board?.promotedFromGenerationId ? `${id}:promote:${board.promotedFromGenerationId}` : id;
    saveCanvasIntent(project, intentId, { revision, key: idempotencyKey, seed, documentId: id, ...target });
    try {
      const send = () => request<CanvasGeneration>(`${path(project, id)}/generate`, { method: "POST", body: JSON.stringify({ revision, idempotencyKey, seed, approved: true, ...target }) });
      let result: CanvasGeneration;
      try { result = await send(); }
      catch (error) {
        if (!(error instanceof ApiError) || error.status !== 422 || !error.message.includes("Board setup required:")) throw error;
        await requestBoardSetup(board?.profileId ?? "moss-bboxes-v1");
        // Keep the exact saved revision, inputs, seed and idempotency key. Edits
        // made during setup cause the normal server revision check to stop it.
        result = await send();
      }
      saveCanvasIntent(project, intentId); return result;
    }
    catch (error) { if (error instanceof ApiError && error.status >= 400 && error.status < 500) saveCanvasIntent(project, intentId); throw error; }
  },
  select: (project: string, id: string, generationId: string) => request<CanvasDocument>(`${path(project, id)}/select-result`, { method: "POST", body: JSON.stringify({ generationId }) }),
  start: (project: string, id: string, generationId: string) => request<CanvasGeneration>(`${path(project, id)}/generations/${generationId}/start`, { method: "POST" }),
};
