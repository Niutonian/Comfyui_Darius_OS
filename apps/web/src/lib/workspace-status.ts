import type { DariusMood, Health, Job } from "./types";

export function workspaceStatus({ health, loading, error, sync, mood, jobs }: { health?: Health; loading?: boolean; error?: boolean; sync?: string; mood: DariusMood; jobs: Job[] }) {
  const active = jobs.filter(job => ["queued", "running", "cancelling"].includes(job.status));
  const failed = jobs.filter(job => job.status === "failed");
  const localReady = Boolean(health?.components.database?.ready && health?.components.comfyui?.ready);
  if (error || health?.components.database?.ready === false) return { label: "Server unavailable", tone: "error" };
  if (sync === "offline" || sync === "reconnecting" || sync === "connecting") return { label: sync === "offline" ? "Sync offline" : "Sync reconnecting", tone: "error" };
  if (failed.length) return { label: `${failed.length} ${failed.length === 1 ? "job needs" : "jobs need"} attention`, tone: "error" };
  if (active.length) return { label: `${active.length} ${active.length === 1 ? "active job" : "active jobs"}`, tone: "generating" };
  if (mood === "listening") return { label: "Listening", tone: "listening" };
  if (mood === "thinking") return { label: "Planning", tone: "planning" };
  if (mood === "speaking") return { label: "Speaking", tone: "speaking" };
  return { label: loading ? "Checking services" : localReady ? "Local ready" : "Local unavailable", tone: localReady ? "ready" : "neutral" };
}
