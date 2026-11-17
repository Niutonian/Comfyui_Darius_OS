import { IMAGE_EDIT, type CanvasProfile } from "./canvas-profile";
import type { ImageRecipeConfig, MossBoard, VideoConfig, VideoInput, VideoMode } from "./moss-workspace";
import type { Asset } from "./types";

/** The MIME type for project assets dragged between windows and the canvas. */
export const ASSET_MIME = "application/x-darius-asset";

export type DropResult<T> = { ok: true; value: T } | { ok: false; reason: string };

/** Which input each image-taking video mode expects, and how many it accepts. */
const videoRoles: Partial<Record<VideoMode, { role: VideoInput["role"]; limit: number }>> = {
  "animate-image": { role: "starting-frame", limit: 1 },
  "camera-direction": { role: "camera-source", limit: 1 },
  "reference-video": { role: "subject", limit: 9 },
};

export function withImageInput(config: ImageRecipeConfig, asset: Asset): DropResult<ImageRecipeConfig> {
  if (asset.kind !== "image") return { ok: false, reason: "Image boards take images." };
  const draft = config.drafts[IMAGE_EDIT];
  if (draft.inputs.some(input => input.assetId === asset.id)) return { ok: false, reason: "That image is already an input of this board." };
  if (draft.inputs.length >= 10) return { ok: false, reason: "This board already has 10 image inputs." };
  const inputs = [...draft.inputs, { id: crypto.randomUUID(), assetId: asset.id, assetVersionId: asset.content_hash, mediaKind: "image" as const, token: draft.inputs.length + 1 }];
  return { ok: true, value: { ...config, activeProfile: IMAGE_EDIT, drafts: { ...config.drafts, [IMAGE_EDIT]: { ...draft, inputs } } } };
}

export function withVideoInput(config: VideoConfig, asset: Asset, mode: VideoMode = config.activeMode): DropResult<VideoConfig> {
  const slot = videoRoles[mode];
  if (!slot) return { ok: false, reason: "This video mode takes a source video, not an image. Choose another mode first." };
  if (asset.kind !== "image") return { ok: false, reason: "Drop an image here to use it as a video input." };
  const draft = config.modeDrafts[mode];
  if (draft.inputs.length >= slot.limit) return { ok: false, reason: "Clear the current input in this video mode before replacing it." };
  const inputs = [...draft.inputs, { id: crypto.randomUUID(), assetId: asset.id, assetVersionId: asset.content_hash, mediaKind: "image" as const, role: slot.role, token: draft.inputs.length + 1 }];
  return { ok: true, value: { ...config, activeMode: mode, modeDrafts: { ...config.modeDrafts, [mode]: { ...draft, inputs } } } };
}

export const videoProfile = (mode: VideoMode) => `minimax-h3-${mode}-v1` as CanvasProfile;

/** Boards an image can be dropped onto directly; other boards get a new image board beside them. */
export function acceptsImage(board: MossBoard) {
  return board.kind === "minimax-h3-video" || (board.kind === "image-recipe" && board.settings.image?.activeProfile === IMAGE_EDIT);
}

/** Dropped OS files Darius can turn into boards. */
export const droppableFile = (file: File) => /^image\/(png|jpeg|webp|gif)$/.test(file.type);
