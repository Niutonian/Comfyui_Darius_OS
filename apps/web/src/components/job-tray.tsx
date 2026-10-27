"use client";

import { CheckCircle2, ChevronDown, ChevronUp, Clock3, LoaderCircle, Play, TriangleAlert, X } from "lucide-react";
import { useRef, useState } from "react";
import { useDariusStore } from "@/lib/store";
import { api } from "@/lib/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/queries";
import type { Job } from "@/lib/types";
import { renderJobText, RenderResultButton } from "./render-job-status";
import { formatDate, titleCase } from "@/lib/utils";
import { jobName } from "@/lib/chat-labels";

function StatusIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle2 className="job-complete" size={16} />;
  if (status === "failed") return <TriangleAlert className="job-failed" size={16} />;
  if (status === "running") return <LoaderCircle className="spin" size={16} />;
  return <Clock3 size={16} />;
}

export function JobTray({ jobs, hasError, mobileModal = false }: { jobs: Job[]; hasError: boolean; mobileModal?: boolean }) {
  const { trayOpen, setTrayOpen, setSelection, activeProjectId } = useDariusStore();
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const acting = useRef(false);
  async function act(job: Job, action: "cancel" | "retry" | "start") {
    if (acting.current) return;
    acting.current = true; setBusyId(job.id); setError("");
    try {
      const updated = await (action === "start" ? api.startRenderJob(job.id) : action === "cancel" ? api.cancelJob(job.id) : api.retryJob(job.id));
      queryClient.setQueryData(queryKeys.job(updated.id), updated);
      await queryClient.invalidateQueries({ queryKey: queryKeys.projectJobs(job.project_id) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.jobRun(job.id) });
    } catch (err) { setError(err instanceof Error ? err.message : "Could not update this job. Try again."); }
    finally { acting.current = false; setBusyId(null); }
  }
  const active = jobs.filter((job) => ["queued", "running", "cancelling"].includes(job.status)).length;
  return (
    <section aria-label="Background jobs" role={mobileModal && trayOpen ? "dialog" : undefined} aria-modal={mobileModal && trayOpen ? true : undefined} className={`job-tray ${trayOpen ? "open" : ""}`}>
      <button aria-expanded={trayOpen} className="tray-handle" onClick={() => setTrayOpen(!trayOpen)} type="button">
        <span><i className={active ? "pulse" : ""} /> Background jobs</span>
        <span>{hasError ? "Unavailable" : active ? `${active} active` : `0 active · ${jobs.length} in history`}{trayOpen ? <ChevronDown size={16} /> : <ChevronUp size={16} />}</span>
      </button>
      {trayOpen ? <div className="tray-content">
        <div className="tray-title"><strong>Background work</strong><span>Saved in this project</span><button aria-label="Close job tray" className="icon-button" onClick={() => setTrayOpen(false)} type="button"><X size={15} /></button></div>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <h3 className="job-section-title">Active &amp; queued · {active}</h3>
        {!active ? <p className="tray-empty">No active jobs. New generation jobs appear here.</p> : null}
        {jobs.filter(job => ["queued", "running", "cancelling"].includes(job.status)).map(job => (
          <div className="job-row" key={job.id} onClick={() => setSelection({ type: "job", id: job.id })} role="button" tabIndex={0} onKeyDown={(event) => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); setSelection({ type: "job", id: job.id }); } }}>
            <StatusIcon status={job.status} />
            <span><strong>{jobName(job)}</strong><small>{job.job_type === "timeline_render" ? renderJobText(job) : job.status_message}</small><small className="job-provider">{job.provider === "bfl" ? "Cloud · BFL" : job.provider === "local-comfyui" || job.provider.includes("comfy") ? "Local · ComfyUI" : titleCase(job.provider)}</small></span>
            <span className={`job-progress ${job.indeterminate_progress && job.status === "running" ? "is-indeterminate" : ""}`}><i style={{ width: `${job.indeterminate_progress && job.status === "running" ? 100 : Math.round(job.progress * 100)}%` }} /></span>
            <em>{job.status === "running" ? job.indeterminate_progress ? "Running" : `${Math.round(job.progress * 100)}%` : formatDate(job.created_at)}</em>
            <span className="job-actions"><RenderResultButton job={job} projectId={activeProjectId} />{job.job_type === "timeline_render" && job.status === "queued" ? <button className="secondary-button job-start-render" disabled={Boolean(busyId)} aria-label={`Start render ${job.id.slice(0, 8)}`} onClick={(event) => { event.stopPropagation(); void act(job, "start"); }} type="button">{busyId === job.id ? <LoaderCircle size={13} className="spin" /> : <Play size={13} />}Start render</button> : null}{["queued", "running", "cancelling"].includes(job.status) ? <button aria-label={`Cancel ${job.id.slice(0, 8)}`} className="icon-button" disabled={Boolean(busyId)} onClick={(event) => { event.stopPropagation(); void act(job, "cancel"); }} type="button">×</button> : null}{["failed", "cancelled"].includes(job.status) ? <button aria-label={`Retry ${job.id.slice(0, 8)}`} className="icon-button" disabled={Boolean(busyId)} onClick={(event) => { event.stopPropagation(); void act(job, "retry"); }} type="button">↻</button> : null}</span>
          </div>
        ))}
        <details className="job-history" open={active === 0 ? true : undefined}><summary>History · {jobs.length - active} saved jobs</summary>
        {jobs.filter(job => !["queued", "running", "cancelling"].includes(job.status)).map(job => (
          <div className="job-row" key={job.id} onClick={() => setSelection({ type: "job", id: job.id })} role="button" tabIndex={0} onKeyDown={(event) => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); setSelection({ type: "job", id: job.id }); } }}>
            <StatusIcon status={job.status} />
            <span><strong>{jobName(job)}</strong><small>{job.job_type === "timeline_render" ? renderJobText(job) : job.status_message}</small><small className="job-provider">{job.provider === "bfl" ? "Cloud · BFL" : job.provider === "local-comfyui" || job.provider.includes("comfy") ? "Local · ComfyUI" : titleCase(job.provider)}</small></span>
            <span className={`job-progress ${job.indeterminate_progress && job.status === "running" ? "is-indeterminate" : ""}`}><i style={{ width: `${job.indeterminate_progress && job.status === "running" ? 100 : Math.round(job.progress * 100)}%` }} /></span>
            <em>{job.status === "running" ? job.indeterminate_progress ? "Running" : `${Math.round(job.progress * 100)}%` : formatDate(job.created_at)}</em>
            <span className="job-actions"><RenderResultButton job={job} projectId={activeProjectId} />{job.job_type === "timeline_render" && job.status === "queued" ? <button className="secondary-button job-start-render" disabled={Boolean(busyId)} aria-label={`Start render ${job.id.slice(0, 8)}`} onClick={(event) => { event.stopPropagation(); void act(job, "start"); }} type="button">{busyId === job.id ? <LoaderCircle size={13} className="spin" /> : <Play size={13} />}Start render</button> : null}{["queued", "running", "cancelling"].includes(job.status) ? <button aria-label={`Cancel ${job.id.slice(0, 8)}`} className="icon-button" disabled={Boolean(busyId)} onClick={(event) => { event.stopPropagation(); void act(job, "cancel"); }} type="button">×</button> : null}{["failed", "cancelled"].includes(job.status) ? <button aria-label={`Retry ${job.id.slice(0, 8)}`} className="icon-button" disabled={Boolean(busyId)} onClick={(event) => { event.stopPropagation(); void act(job, "retry"); }} type="button">↻</button> : null}</span>
          </div>
        ))}
        </details>
      </div> : null}
    </section>
  );
}
