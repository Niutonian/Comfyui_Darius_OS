import type { BoardSettings } from "./moss-workspace";

export const MOSS = "moss-bboxes-v1";
export const LEGACY_FIBO_FAST = "fibo-fast-experimental-v1";
export const FIBO_FAST = "fibo-fast-turbo-v2";
export const FIBO_DEV = "fibo-dev-v1";
export const H3_ANIMATE = "minimax-h3-animate-image-v1";
export const H3_CAMERA = "minimax-h3-camera-direction-v1";
export const H3_BODY_SWAP = "minimax-h3-body-swap-v1";
export const H3_REFERENCE = "minimax-h3-reference-video-v1";
export const IMAGE_FLUX = "flux3-klein-t2i-v1";
export const IMAGE_KREA = "krea2-turbo-t2i-v1";
export const IMAGE_QWEN = "qwen21-t2i-v1";
export const IMAGE_EDIT = "qwen21-edit-v1";
export type CanvasProfile = typeof IMAGE_FLUX | typeof IMAGE_KREA | typeof IMAGE_QWEN | typeof IMAGE_EDIT | typeof H3_ANIMATE | typeof H3_CAMERA | typeof H3_REFERENCE | typeof H3_BODY_SWAP | typeof MOSS | typeof FIBO_FAST | typeof FIBO_DEV | typeof LEGACY_FIBO_FAST;
export const canvasProfiles: Record<CanvasProfile, { name: string; family: string; action: string; settings: string }> = {
  [IMAGE_FLUX]: { name: "FLUX 3 Klein", family: "Image", action: "Generate image", settings: "50 steps · CFG 3.5 · euler / simple" },
  [IMAGE_KREA]: { name: "Krea 2 Turbo", family: "Image", action: "Generate image", settings: "8 steps · CFG 1 · euler / simple" },
  [IMAGE_QWEN]: { name: "Qwen Image 2.1", family: "Image", action: "Generate image", settings: "25 steps · CFG 1 · euler / simple" },
  [IMAGE_EDIT]: { name: "Qwen Image 2.1 · Edit", family: "Image", action: "Generate edit", settings: "25 steps · CFG 1 · pinned image references" },
  [H3_ANIMATE]: { name: "Animate image", family: "MiniMax H3", action: "Generate video", settings: "4 steps · euler / simple · generated audio" },
  [H3_CAMERA]: { name: "Camera direction", family: "MiniMax H3", action: "Generate video", settings: "Camera LoRA · Turbo 8 / Base 20 steps" },
  [H3_BODY_SWAP]: { name: "Body swap", family: "MiniMax H3", action: "Generate video", settings: "Character image + source video · 8 steps · source audio" },
  [H3_REFERENCE]: { name: "Reference video", family: "MiniMax H3", action: "Generate video", settings: "12-step split at 8 · 1.5× latent upscale · generated audio" },
  [MOSS]: { name: "MOSS", family: "MOSS", action: "Generate composition", settings: "25 steps · CFG 2.5 · er_sde / simple" },
  [LEGACY_FIBO_FAST]: { name: "Fast preview · legacy Dev weights", family: "FIBO", action: "Generate preview", settings: "4 steps · CFG 1 · euler / simple" },
  [FIBO_FAST]: { name: "Fast preview · Turbo · experimental", family: "FIBO", action: "Generate preview", settings: "4 steps · CFG 1 · euler / simple" },
  [FIBO_DEV]: { name: "Dev render", family: "FIBO", action: "Generate with Dev", settings: "30 steps · CFG 5 · euler / simple" },
};
export function switchCanvasProfile(settings: BoardSettings, profile: CanvasProfile): BoardSettings {
  return { ...settings, adapterVersion: profile, seed: settings.providerSettings?.[profile]?.seed ?? (profile === FIBO_FAST ? settings.providerSettings?.[LEGACY_FIBO_FAST]?.seed ?? null : null),
    providerSettings: { ...settings.providerSettings, [settings.adapterVersion]: { seed: settings.seed } } };
}
export function canvasSeed(value: string, profile: CanvasProfile): number | string | null {
  if (!value.trim()) return null;
  const maximum = profile === MOSS ? BigInt("4294967295") : BigInt("18446744073709551615");
  if (!/^\d+$/.test(value) || BigInt(value) > maximum) throw new Error(`Seed must be between 0 and ${maximum.toLocaleString("en-US")}`);
  return profile === MOSS ? Number(value) : BigInt(value).toString();
}
