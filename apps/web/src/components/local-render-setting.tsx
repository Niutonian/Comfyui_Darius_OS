"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

export function LocalRenderSetting({ projectId, busy = false, modes = false, compact = false }: { projectId: string; busy?: boolean; modes?: boolean; compact?: boolean }) {
  const client = useQueryClient();
  const queryKey = ["local-rendering", projectId];
  const setting = useQuery({ queryKey, queryFn: () => api.localRendering(projectId) });
  const enabled = setting.data?.enabled ?? false;
  const loading = !setting.data;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function change(next: boolean) {
    setSaving(true); setError("");
    try { client.setQueryData(queryKey, await api.setLocalRendering(projectId, next)); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save local rendering permission"); }
    finally { setSaving(false); }
  }

  return <div className="local-render-setting">
    {compact ? <div className="route-pills" role="group" aria-label="Generation mode for this project" title="Saved separately for each project">
      <button aria-pressed={!loading && !enabled} disabled={loading || saving} onClick={() => void change(false)} type="button">Manual</button>
      <button aria-pressed={!loading && enabled} disabled={loading || saving || busy} onClick={() => void change(true)} type="button">Full auto</button>
    </div> : modes ? <div className="theme-options" role="group" aria-label="Execution mode">
      {[{ enabled: false, title: "Manual", detail: "Review and approve each render before it enters the queue." }, { enabled: true, title: "Full auto", detail: "Ask by voice or chat. Darius prepares and queues supported local renders automatically." }].map((mode) => <button key={mode.title} className={`theme-option ${!loading && enabled === mode.enabled ? "selected" : ""}`} aria-pressed={!loading && enabled === mode.enabled} disabled={loading || saving || (busy && mode.enabled)} onClick={() => void change(mode.enabled)} type="button"><span><strong>{mode.title}</strong><small>{mode.detail}</small></span></button>)}
    </div> : <label><input type="checkbox" checked={enabled} disabled={loading || saving || (busy && !enabled)} onChange={(event) => void change(event.target.checked)} /> Full auto · local rendering</label>}
    {compact ? <span className="sr-only" role="status">{saving ? "Saving project mode" : loading ? "Loading project mode" : enabled ? "Full auto enabled for this project" : "Manual mode for this project"}</span> : <small>{saving ? "Saving permission…" : loading ? "Loading permission…" : enabled ? "Voice and chat can start verified local renders for this project, including supported H3 workflows." : "Ask before starting renders for this project."} External or unverified workflows still need approval.</small>}
    {error || setting.error ? <p role="alert">{error || setting.error?.message} {loading ? <button className="secondary-button" type="button" onClick={() => void setting.refetch()}>Retry setting</button> : null}</p> : null}
  </div>;
}
