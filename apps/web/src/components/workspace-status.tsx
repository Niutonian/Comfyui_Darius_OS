"use client";
import { ChevronDown, RefreshCw } from "lucide-react";
import type { DariusMood, Health, Job } from "@/lib/types";
import { useDariusStore } from "@/lib/store";
import { workspaceStatus } from "@/lib/workspace-status";
import { rememberWorkspaceValue } from "@/lib/workspace-session";

export function WorkspaceStatus({ health, loading, error, sync, mood, jobs, onRefresh }: { health?: Health; loading?: boolean; error?: boolean; sync?: string; mood: DariusMood; jobs: Job[]; onRefresh: () => void }) {
  const status = workspaceStatus({ health, loading, error, sync, mood, jobs });
  const active = jobs.filter(job => ["queued", "running", "cancelling"].includes(job.status));
  const failed = jobs.filter(job => job.status === "failed");
  function navigate(action: "jobs" | "services", element: HTMLElement) {
    element.closest("details")?.removeAttribute("open");
    if (action === "jobs") useDariusStore.getState().setTrayOpen(true);
    else { rememberWorkspaceValue("settings:category", "services"); useDariusStore.getState().setView("settings"); }
  }
  return <details className="workspace-status" onKeyDown={event => { if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector<HTMLElement>("summary")?.focus(); } }}>
    <summary aria-label={`Workspace status: ${status.label}`}><span className={`agent-status tone-${status.tone}`} role="status"><i /><span>{status.label}</span></span><ChevronDown size={12} /></summary>
    <div className="workspace-status-details">
      <strong>Workspace status</strong>
      <p><span>Project sync</span><span>{sync === "live" ? "Live sync" : sync === "polling" ? "Periodic sync" : sync === "offline" ? "Offline · changes will reconnect" : sync ? "Reconnecting" : "No project selected"}</span></p>
      <p><span>Darius</span><span>{mood === "thinking" ? "Planning" : mood === "listening" ? "Listening" : mood === "speaking" ? "Speaking" : "Idle"}</span></p>
      <button className="text-button" type="button" onClick={event => navigate("jobs", event.currentTarget)}>{active.length} active · {failed.length} failed · {jobs.length - active.length} in history</button>
      <div className="status-provider-list">{Object.entries(health?.components ?? {}).map(([name, service]) => <p key={name}><span>{name.replaceAll("_", " ")}</span><span>{service.ready ? "Available" : service.configured ? "Configured · unavailable" : "Not configured"}</span></p>)}</div>
      {error ? <p role="alert">The server health check failed. Saved workspace content is kept.</p> : null}
      <footer><button className="secondary-button" onClick={onRefresh} type="button"><RefreshCw size={14} />Recheck</button><button className="text-button" onClick={event => navigate("services", event.currentTarget)} type="button">Settings</button></footer>
    </div>
  </details>;
}
