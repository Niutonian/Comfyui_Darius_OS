import type { Asset, Job } from "./types";

export function readableName(value: unknown, fallback = "Generation"): string {
  if (typeof value !== "string") return fallback;
  const name = value
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, "")
    .replace(/\b(?:task|assistant|job|asset)-[a-f0-9]{16,64}\b/gi, "")
    .replace(/[-_][a-f0-9]{8}(?=[-_]\d{1,3}(?:\.[a-z0-9]+)?$)/gi, "")
    .replace(/\.(?:png|jpe?g|webp|gif|mp4|webm|mov|wav|mp3)$/i, "")
    .replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  return name ? name.slice(0, 90) : fallback;
}

export function assetName(asset: Asset): string {
  return [asset.metadata.display_name, asset.metadata.prompt, asset.metadata.original_filename, asset.metadata.filename]
    .map((name) => readableName(name, "")).find(Boolean) || asset.kind[0].toUpperCase() + asset.kind.slice(1);
}

export function jobName(job: Job): string {
  return readableName(job.display_name, job.job_type === "timeline_render" ? "Timeline export" : "Generation");
}

/** Speech-only: never change the saved text, IDs, URLs or diagnostic records. */
export function spokenText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " Technical details are available in chat. ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/gi, "the linked resource")
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, "")
    .replace(/\b(?:task|assistant|job|asset)-[a-f0-9]{8,64}\b/gi, "")
    .replace(/\b[\w.-]+\.(?:png|jpe?g|webp|gif|mp4|webm|mov|wav|mp3)\b/gi, (name) => readableName(name, "the asset"))
    .replace(/\b[0-9a-f]{8,64}\b/gi, "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s+/g, " ").replace(/\s+([,.;:!?])/g, "$1").trim();
}
