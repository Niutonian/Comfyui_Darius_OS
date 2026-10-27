"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api-client";
import { queryKeys } from "@/lib/queries";
import type { Asset, Job, Message } from "@/lib/types";
import { AssetViewer } from "./asset-preview";
import { jobName } from "@/lib/chat-labels";
import { CreativeMessage } from "./creative-message";

export function renderJobText(job: Job) {
  const states: Record<string, string> = { queued: "Queued · waiting for a worker", running: `Rendering · ${Math.min(99, Math.max(0, Math.round(job.progress * 100)))}%`, completed: "Completed · 100%", failed: "Failed", cancelled: "Cancelled", cancelling: "Cancelling" };
  return `${jobName(job)}: ${states[job.status] ?? job.status}`;
}
export function useRenderJob(jobId: string, projectId: string | null, initialJob?: Job) {
  return useQuery({ queryKey: queryKeys.job(jobId), queryFn: () => api.job(jobId), enabled: Boolean(projectId), initialData: initialJob?.project_id === projectId ? initialJob : undefined, refetchInterval: (query) => ["completed", "failed", "cancelled"].includes(query.state.data?.status ?? "") ? false : 2500, retry: 1 });
}

export function RenderResultButton({ job, projectId }: { job: Job; projectId: string | null }) {
  const [asset, setAsset] = useState<Asset | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const outputIds = job.output_asset_ids ?? [];
  if (job.project_id !== projectId || job.status !== "completed" || !outputIds.length) return null;
  async function open() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const output = await api.asset(outputIds[0]);
      if (output.project_id !== projectId || !["image", "video", "audio"].includes(output.kind)) throw new Error("This result is unavailable in the current project.");
      setAsset(output);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not open this result. Try again."); }
    finally { setBusy(false); }
  }
  return <div className="render-result-action" onClick={(event) => event.stopPropagation()}>
    <button className="secondary-button" type="button" disabled={busy} onClick={() => void open()}>{busy ? "Opening…" : "Open result"}</button>
    {error ? <small className="form-error" role="alert">{error}</small> : null}
    {asset && asset.project_id === projectId && outputIds.includes(asset.id) ? <AssetViewer asset={asset} onSelect={setAsset} onClose={() => setAsset(null)} /> : null}
  </div>;
}

export function RenderJobStatus({ jobId, projectId, initialJob }: { jobId: string; projectId: string | null; initialJob?: Job }) {
  const query = useRenderJob(jobId, projectId, initialJob);
  const job = query.data?.project_id === projectId ? query.data : undefined;
  return <div className="live-render-status"><p role="status">{query.isError ? "Could not refresh render status. The last status may be outdated." : job ? renderJobText(job) : query.data ? "Render not found in this project." : "Loading render status…"}</p>
    {query.isError ? <button className="text-button" type="button" onClick={() => void query.refetch()}>Refresh render status</button> : null}
    {job?.error_detail ? <p className="form-error" role="alert">{job.error_detail}</p> : null}
    {job && !query.isError ? <RenderResultButton job={job} projectId={projectId} /> : null}
  </div>;
}

/** Replace only job-receipt prose, never a user's quote or normal assistant narrative. */
export function RenderMessageText({ message, projectId }: { message: Message; projectId: string | null }) {
  const receipt = message.role === "assistant" && /^Render jobs?:?\s+(?:[0-9a-f]{8}(?:-[0-9a-f-]{1,28})?|job-[\w-]+)\b/i.test(message.content.trim());
  const ids = messageJobIds(message.metadata);
  const reviewed = message.role === "assistant" && message.metadata.reviewed_generation === true;
  if ((!receipt && !reviewed) || !ids.length) return message.role === "assistant" && projectId ? <CreativeMessage key={`${projectId}:${message.id}`} message={message} projectId={projectId} /> : <p>{message.content}</p>;
  const status = ids.length === 1 ? <ReceiptText jobId={ids[0]} projectId={projectId} /> : <p>Render jobs · current statuses below</p>;
  return reviewed ? <>{status}<details><summary>Original reply before approval</summary><p>{message.content}</p></details></> : status;
}
export function messageJobIds(metadata: Message["metadata"]): string[] {
  return [...new Set([metadata.job_id, metadata.local_render_job_id,
    ...(Array.isArray(metadata.job_ids) ? metadata.job_ids : []), ...(Array.isArray(metadata.local_render_job_ids) ? metadata.local_render_job_ids : []),
    ...(Array.isArray(metadata.generation_drafts) ? metadata.generation_drafts.flatMap((item) => item && typeof item === "object" ? [item.job_id] : []) : []),
  ].filter((id): id is string => typeof id === "string" && Boolean(id)))];
}
function ReceiptText({ jobId, projectId }: { jobId: string; projectId: string | null }) {
  const query = useRenderJob(jobId, projectId);
  return <p>{query.isError ? "Render status could not be refreshed. Check Background jobs." : query.data?.project_id === projectId ? renderJobText(query.data) : "Checking current render status…"}</p>;
}
