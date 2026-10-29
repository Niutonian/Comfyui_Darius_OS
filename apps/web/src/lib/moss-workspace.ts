import type { CanvasProfile } from "./canvas-profile";
import { canvasApi, type CanvasDocument, type CanvasGeneration } from "./canvas-api";
import { request } from "./api-client";
import { readWorkspaceValue, rememberWorkspaceValue } from "./workspace-session";
import { sameContent, type CanvasContent, type CanvasHistory } from "./canvas-document";

export type ImageProfile = "flux3-klein-t2i-v1" | "krea2-turbo-t2i-v1" | "qwen21-t2i-v1" | "qwen21-edit-v1";
export type ImageInput = { id: string; assetId: string; assetVersionId: string; mediaKind: "image"; token: number };
export type ImageDraft = { prompt: string; negativePrompt: string; inputs: ImageInput[]; preset: "square" | "poster" | "photo" | "portrait" | "standard" | "vertical" | "wide" | "ultrawide"; megapixels: 1 | 4; steps: number; cfg: number; seed: string | null; enhance: boolean; styleEnabled: boolean; styleLora: string; styleStrength: number; styleText: string; followSource: boolean; referenceResolution: 0 | 1024 | 2048 };
export type ImageRecipeConfig = { schemaVersion: 1; activeProfile: ImageProfile; drafts: Record<ImageProfile, ImageDraft> };
export type VideoMode = "animate-image" | "camera-direction" | "reference-video";
export type VideoInput = { id: string; assetId: string; assetVersionId: string; mediaKind: "image"; role: "starting-frame" | "camera-source" | "subject" | "environment" | "style"; token: number };
export type VideoDraft = { prompt: string; camera: string; audio: string; inputs: VideoInput[]; seconds: number; turbo: boolean; upscaleDevice?: "cuda" | "cpu"; preset?: ImageDraft["preset"]; resolution?: "native" | "480p" | "720p" | "1080p" };
export type VideoConfig = { schemaVersion: 1; family: "minimax-h3"; activeMode: VideoMode; modeDrafts: Record<VideoMode, VideoDraft> };
export type Placement = { boardId: string; x: number; y: number; displayWidth: number; displayHeight: number; order: number };
export type VisualReference = { id: string; sourceBoardId: string; sourceGenerationId: string; assetId: string; assetVersionId: string; role: "visual-note" };
export type BoardSettings = { adapterVersion: CanvasProfile; seed: number | string | null; providerSettings?: Partial<Record<CanvasProfile, { seed: number | string | null }>>; references: VisualReference[]; video?: VideoConfig | null; image?: ImageRecipeConfig | null };
export type VideoRecovery = { stage: string; outOfMemory: boolean; message: string; canResumeFinalOnly: boolean; explanation: string };
export type BoardRun = { recovery?: VideoRecovery; intermediateAssetIds?: string[] } & Pick<CanvasGeneration, "id" | "jobId" | "revision" | "seed" | "status" | "statusMessage" | "error" | "assetIds">;
export type MossBoard = { id: string; projectId: string; documentId: string; name: string; kind: "moss-t2i" | "fibo-t2i" | "minimax-h3-video" | "image-recipe"; revision: number; documentRevision: number; settings: BoardSettings; archived: boolean; artboard: { width: number; height: number; preset: string }; prompt: string; regionCount: number; layout: { id: string; kind: string; rect: number[] }[]; activeResult: BoardRun | null; previewAssetId: string | null; latest: BoardRun | null; jobs: BoardRun[]; newResult: boolean };
export type ProjectWorkspace = { projectId: string; schemaVersion: 1; revision: number; placements: Placement[]; boards: MossBoard[]; capacity: number; queuePolicy: string };
export type CanvasDraft = { history: CanvasHistory; revision: number; saved: CanvasContent; pending?: { revision: number; key: string; seed: number | null } };
export type BoardContext = { boardId: string; documentId: string; documentRevision: number; boardRevision: number; name: string; seed?: number | string | null; profileId?: CanvasProfile };
export type SelectedBoardContext = BoardContext & { prepare: () => Promise<BoardContext> };
const root = (project: string) => `/projects/${encodeURIComponent(project)}/canvas-workspace`;
export const mossApi = {
  get: (project: string) => request<ProjectWorkspace>(root(project)),
  layout: (project: string, revision: number, placements: Placement[]) => request<ProjectWorkspace>(`${root(project)}/layout`, { method: "POST", body: JSON.stringify({ revision, placements }) }),
  add: (project: string, input: { name?: string; x: number; y: number; duplicateBoardId?: string; settings?: BoardSettings; content?: CanvasContent }) => request<{ boardId: string; workspace: ProjectWorkspace }>(`${root(project)}/boards`, { method: "POST", body: JSON.stringify(input) }),
  save: (project: string, board: MossBoard, settings = board.settings, archived = board.archived) => request<MossBoard>(`${root(project)}/boards/${board.id}`, { method: "POST", body: JSON.stringify({ revision: board.revision, settings, archived }) }),
  cancel: (project: string, board: string, job: string) => request(`${root(project)}/boards/${board}/cancel/${job}`, { method: "POST" }),
};
const savers = new Map<string, () => Promise<CanvasDocument | undefined>>();
export function registerCanvasSaver(project: string, document: string, save: () => Promise<CanvasDocument | undefined>) {
  const key = `${project}:${document}`; savers.set(key, save);
  return () => { if (savers.get(key) === save) savers.delete(key); };
}
export async function prepareBoard(project: string, board: MossBoard): Promise<BoardContext> {
  if (board.archived) throw new Error("Restore this archived board before generating or editing its draft.");
  if (board.kind === "minimax-h3-video") {
    const key = `h3:${project}:${board.id}`, draft = readWorkspaceValue<VideoConfig>(`${key}:draft`);
    if (draft && JSON.stringify(draft) !== JSON.stringify(board.settings.video)) {
      if (readWorkspaceValue<number>(`${key}:base`) !== board.revision) throw new Error("Video settings changed on another device. Reload the saved draft before generating.");
      const profile = `minimax-h3-${draft.activeMode}-v1` as CanvasProfile;
      board = await mossApi.save(project, board, { ...board.settings, adapterVersion: profile, video: draft });
      rememberWorkspaceValue(`${key}:base`, board.revision);
    }
  }
  if (board.kind === "image-recipe") {
    const key = `image-recipe:${project}:${board.id}`, draft = readWorkspaceValue<ImageRecipeConfig>(`${key}:draft`);
    if (draft && JSON.stringify(draft) !== JSON.stringify(board.settings.image)) {
      if (readWorkspaceValue<number>(`${key}:base`) !== board.revision) throw new Error("Image settings changed on another device. Reload the saved draft before generating.");
      board = await mossApi.save(project, board, { ...board.settings, adapterVersion: draft.activeProfile, seed: draft.drafts[draft.activeProfile].seed, image: draft });
      rememberWorkspaceValue(`${key}:base`, board.revision);
    }
  }
  const save = savers.get(`${project}:${board.documentId}`), key = `canvas:${project}:${board.documentId}:draft`;
  if (save) await save();
  let draft = readWorkspaceValue<CanvasDraft | null>(key);
  if (draft && !sameContent(draft.history.present, draft.saved)) {
    if (save) throw new Error("The board changed while saving. Your draft is retained; submit again once saved.");
    const snapshot = draft.history.present, saved = await canvasApi.save(project, board.documentId, draft.revision, snapshot);
    const current = readWorkspaceValue<CanvasDraft | null>(key);
    if (current) rememberWorkspaceValue(key, { ...current, revision: saved.revision, saved: snapshot });
    draft = readWorkspaceValue<CanvasDraft | null>(key);
    if (draft && !sameContent(draft.history.present, draft.saved)) throw new Error("This board changed while saving. Submit again once saved.");
  }
  const remote = await canvasApi.get(project, board.documentId);
  if (draft && sameContent(draft.history.present, draft.saved) && remote.revision > draft.revision) {
    draft = { ...draft, revision: remote.revision, saved: remote.content, history: { past: [], present: remote.content, future: [] } };
    rememberWorkspaceValue(key, draft);
  }
  return { boardId: board.id, documentId: board.documentId, boardRevision: board.revision, profileId: board.settings.adapterVersion, seed: board.settings.seed, documentRevision: draft?.revision ?? remote.revision, name: draft?.history.present.name ?? remote.content.name };
}
export function fitPlacements(placements: Placement[], size: { width: number; height: number }) {
  if (!placements.length) return { x: size.width / 2 - 180, y: 60, scale: 1 };
  const left = Math.min(...placements.map(p => p.x)), top = Math.min(...placements.map(p => p.y));
  const width = Math.max(...placements.map(p => p.x + p.displayWidth)) - left, height = Math.max(...placements.map(p => p.y + p.displayHeight)) - top;
  const scale = Math.min(1.3, Math.max(.15, Math.min((size.width - 100) / width, (size.height - 100) / height)));
  return { scale, x: (size.width - width * scale) / 2 - left * scale, y: (size.height - height * scale) / 2 - top * scale };
}
export function worldPoint(point: { x: number; y: number }, camera: { x: number; y: number; scale: number }) {
  return { x: (point.x - camera.x) / camera.scale, y: (point.y - camera.y) / camera.scale };
}
export function fitCardToArtwork(placement: Placement, artwork: { width: number; height: number }): Placement {
  if (!(artwork.width > 0 && artwork.height > 0)) return placement;
  const ratio = artwork.width / artwork.height;
  const chrome = 92;
  const height = Math.max(350, Math.min(900, placement.displayWidth / ratio + chrome));
  return { ...placement, displayWidth: Math.max(280, Math.min(800, (height - chrome) * ratio)), displayHeight: height };
}
export function boardStatus(board: MossBoard, preparing = false, requestError?: string) {
  if (preparing) return "Preparing";
  if (board.jobs.some(j => j.status === "running" || j.status === "cancelling")) return "Running";
  if (board.jobs.some(j => j.status === "queued")) return "Queued";
  if (requestError) return "Needs attention";
  if (board.latest?.status === "failed") return "Failed";
  if (board.latest?.status === "cancelled") return "Cancelled";
  if (board.newResult) return "New result";
  return board.activeResult ? "Ready" : "Draft";
}
