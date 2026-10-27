"use client";

import { useKnownAssets } from "@/lib/queries";
import { renderJobText, useRenderJob } from "./render-job-status";
import { AssetPreview } from "./asset-preview";
import { useDariusStore } from "@/lib/store";
import { useState } from "react";
import { Download, Film, Pencil, Pin, Sparkles, RefreshCw } from "lucide-react";
import { api } from "@/lib/api-client";
import { assetName } from "@/lib/chat-labels";
import type { Asset, JobRun } from "@/lib/types";
import type { ResultAction } from "./result-followup";

export function ConversationRender({ jobId, projectId, embedded = false, busy = false, onFollowup }: { jobId: string; projectId: string | null; embedded?: boolean; busy?: boolean; onFollowup?: (asset: Asset, action: ResultAction) => void }) {
  const query = useRenderJob(jobId, projectId);
  const job = query.data?.project_id === projectId ? query.data : undefined;
  const outputs = useKnownAssets(job?.output_asset_ids ?? []);
  const selectedReference = useDariusStore(state => state.activeProjectId === projectId ? state.referenceAssetIds.join("|") : "");
  const [recovery, setRecovery] = useState<JobRun | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  async function checkRetry() {
    if (!job || checking) return;
    setChecking(true); setError("");
    try { const run = await api.jobRun(job.id); if (run.job_id !== job.id) throw new Error("The saved run could not be verified."); setRecovery(run); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not check the saved run."); }
    finally { setChecking(false); }
  }
  const assets = outputs.assets.filter(asset => asset.project_id === projectId && asset.role !== "derivative");
  function selectReference(asset: Asset) {
    const store = useDariusStore.getState();
    if (asset.project_id !== projectId || store.activeProjectId !== projectId || busy) return;
    for (const id of store.referenceAssetIds) store.removeReferenceAsset(id);
    store.addReferenceAsset(asset.id);
  }
  return <div className={`conversation-render result-job result-job-${job?.status ?? "loading"}`}>
    <p role="status">{query.isError ? "Could not refresh render status. The last status may be outdated." : job ? renderJobText(job) : "Loading render status…"}</p>
    {query.isError ? <button className="text-button" type="button" onClick={() => void query.refetch()}>Refresh render status</button> : null}
    {job && ["queued", "running", "cancelling"].includes(job.status) ? <progress aria-label="Render progress" max={100} value={Math.max(0, Math.min(100, Math.round(job.progress * 100)))} /> : null}
    {job?.error_detail ? <details className="result-technical"><summary>What happened</summary><p>{job.error_detail}</p></details> : null}
    {assets.map(asset => <article className="conversation-result-card" key={asset.id} aria-label={`Generated ${asset.kind}: ${assetName(asset)}`}>
      <AssetPreview asset={asset} navigationAssets={assets} />
      <div className="result-card-copy"><strong>{assetName(asset)}</strong><small>{[asset.kind, asset.width && asset.height ? `${asset.width} × ${asset.height}` : "", asset.duration ? `${asset.duration.toFixed(1)}s` : ""].filter(Boolean).join(" · ")}</small></div>
      <div className="result-card-actions" aria-label={`Actions for ${assetName(asset)}`}>
        {asset.kind === "image" ? <button className="secondary-button" type="button" disabled={busy || query.isError} aria-pressed={selectedReference === asset.id} title="Use only this image for the next message, replacing other selected references" onClick={() => selectReference(asset)}><Pin size={14} />Use as reference</button> : null}
        {onFollowup && ["image", "video"].includes(asset.kind) ? <button className="secondary-button" type="button" disabled={busy || query.isError} onClick={() => onFollowup(asset, "edit")}><Pencil size={14} />Edit</button> : null}
        {onFollowup && asset.kind === "image" ? <><button className="secondary-button" type="button" disabled={busy || query.isError} onClick={() => onFollowup(asset, "animate")}><Film size={14} />Animate</button><button className="secondary-button" type="button" disabled={busy || query.isError} onClick={() => onFollowup(asset, "upscale")}><Sparkles size={14} />Upscale</button></> : null}
        <a className="secondary-button" href={api.assetContentUrl(asset.id)} download={downloadName(asset)}><Download size={14} />Download</a>
      </div>
    </article>)}
    {job?.status === "completed" && job.output_asset_ids.length > assets.length ? <small>Some saved previews are still loading or unavailable. <button className="text-button" type="button" onClick={() => useDariusStore.getState().setSelection({ type: "job", id: job.id })}>Inspect saved results</button></small> : null}
    {job && ["failed", "cancelled"].includes(job.status) ? <div className="result-recovery"><button className="secondary-button" type="button" disabled={checking} onClick={() => void checkRetry()}><RefreshCw size={14} />{checking ? "Checking…" : "Retry options"}</button>{recovery ? <div><p>{recovery.recovery_message || "Inspect the saved run before starting another render."}</p>{recovery.retried_by_job_id ? <small>A retry already exists. Check Background jobs before starting another.</small> : null}<small>No render was submitted by this check.</small>{embedded ? <small>Return to chat and open Background jobs to review this saved run.</small> : <button className="text-button" type="button" onClick={() => useDariusStore.getState().setSelection({ type: "job", id: recovery.retried_by_job_id || job.id })}>Inspect saved render</button>}</div> : null}{error ? <p role="alert">{error}</p> : null}</div> : null}
    {!embedded && job?.output_asset_ids.length ? <button className="secondary-button" type="button" onClick={() => useDariusStore.getState().setView("create")}>Open results in Create</button> : null}
  </div>;
}

export function downloadName(asset: Asset) {
  const extensions: Record<string, string> = { "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif", "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov", "audio/wav": ".wav", "audio/mpeg": ".mp3" };
  return assetName(asset).replace(/[<>:"/\\|?*\u0000-\u001f]/g, "-").replace(/[. ]+$/, "") + (extensions[asset.mime_type] || "");
}
