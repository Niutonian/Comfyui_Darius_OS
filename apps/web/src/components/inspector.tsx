"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Box, Database, FileKey2, Map as MapIcon, Scissors, X } from "lucide-react";
import { api } from "@/lib/api-client";
import { queryKeys, useCharacters, useScenes } from "@/lib/queries";
import { useDariusStore } from "@/lib/store";
import type { Asset, Job, Workflow } from "@/lib/types";
import { formatDate, shortId, titleCase } from "@/lib/utils";
import { AssetPreview } from "./asset-preview";
import { assetName } from "@/lib/chat-labels";

export function Inspector({ assets, jobs, workflows, mobileModal = false }: { assets: Asset[]; jobs: Job[]; workflows: Workflow[]; mobileModal?: boolean }) {
  const { selection, projects, activeProjectId, inspectorOpen, setInspectorOpen } = useDariusStore();
  const characters = useCharacters(selection?.type === "project" ? selection.id : selection?.type === "character" ? activeProjectId : null);
  const scenes = useScenes(selection?.type === "project" ? selection.id : selection?.type === "scene" ? activeProjectId : null);
  const character = characters.data?.find((item) => item.id === selection?.id);
  const scene = scenes.data?.find((item) => item.id === selection?.id);
  useEffect(() => {
    if (!inspectorOpen) return;
    const invokingControl = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector(".asset-viewer[open]")) setInspectorOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => { window.removeEventListener("keydown", close); if (invokingControl?.isConnected) invokingControl.focus({ preventScroll: true }); };
  }, [inspectorOpen, setInspectorOpen]);
  const asset = selection?.type === "asset" ? assets.find((item) => item.id === selection.id) : undefined;
  const job = selection?.type === "job" ? jobs.find((item) => item.id === selection.id) : undefined;
  const jobRun = useQuery({
    queryKey: queryKeys.jobRun(job?.id ?? "none"),
    queryFn: () => api.jobRun(job!.id),
    enabled: Boolean(job),
    refetchInterval: job && ["queued", "running", "cancelling"].includes(job.status) ? 2_500 : false,
    retry: 1,
  });
  const workflow = selection?.type === "workflow" ? workflows.find((item) => item.id === selection.id) : undefined;
  const project = selection?.type === "project" ? projects.find((item) => item.id === selection.id) : undefined;
  const provenance = useQuery({
    queryKey: queryKeys.provenance(asset?.id ?? "none"),
    queryFn: () => api.provenance(asset!.id),
    enabled: Boolean(asset),
    retry: 1,
  });

  if (!inspectorOpen) return null;
  return (
    <aside aria-label="Inspector" role={mobileModal ? "dialog" : undefined} aria-modal={mobileModal ? true : undefined} className="inspector">
      <header><span>Inspector</span><button aria-label="Close inspector" className="icon-button" onClick={() => setInspectorOpen(false)} type="button"><X size={17} /></button></header>
      {!selection ? <div className="inspector-empty"><Box size={24} /><p>Select a project item to inspect its details and provenance.</p></div> : null}
      {character ? <InspectorSection icon={<Box size={16} />} title="Character"><h2>{character.name}</h2><p>{character.description}</p><h3>Character prompt</h3><p>{character.canonical_prompt || "No prompt yet."}</p><h3>Continuity</h3><p>{character.continuity_notes || "No continuity notes yet."}</p><h3>Approved references</h3><p>{character.approved_reference_asset_ids.length} linked assets</p></InspectorSection> : null}
      {scene ? <InspectorSection icon={<Box size={16} />} title="Scene"><h2>{scene.title}</h2><p>{scene.description}</p><dl><div><dt>Location</dt><dd>{scene.location || "Not set"}</dd></div><div><dt>Time</dt><dd>{scene.time_of_day || "Not set"}</dd></div><div><dt>Mood</dt><dd>{scene.mood || "Not set"}</dd></div></dl><h3>Screenplay</h3><p style={{ whiteSpace: "pre-wrap" }}>{scene.screenplay_text || "No screenplay yet."}</p></InspectorSection> : null}
      {project ? <InspectorSection icon={<Database size={16} />} title="Project"><h2>{project.name}</h2><p>{project.description || "No project description."}</p><dl>{project.id === activeProjectId ? <div><dt>Assets loaded</dt><dd>{assets.length}</dd></div> : null}<div><dt>Characters</dt><dd>{characters.data?.length ?? "Loading…"}</dd></div><div><dt>Scenes</dt><dd>{scenes.data?.length ?? "Loading…"}</dd></div><div><dt>Created</dt><dd>{formatDate(project.created_at)}</dd></div></dl>{project.id !== activeProjectId ? <button className="primary-button" onClick={() => { useDariusStore.getState().openProject(project.id); setInspectorOpen(false); }} type="button">Open project</button> : null}<details className="metadata-details"><summary>Technical details</summary><dl><div><dt>Project ID</dt><dd>{project.id}</dd></div></dl></details></InspectorSection> : null}
      {workflow ? <InspectorSection icon={<FileKey2 size={16} />} title="Workflow"><h2>{workflow.name}</h2><dl><div><dt>Capability</dt><dd>{titleCase(workflow.capability)}</dd></div><div><dt>Provider</dt><dd>{titleCase(workflow.execution_provider)}</dd></div><div><dt>Output</dt><dd>{workflow.output.kind}</dd></div><div><dt>Version</dt><dd>{workflow.version}</dd></div></dl></InspectorSection> : null}
      {job ? <InspectorSection icon={<Box size={16} />} title="Job"><h2>{titleCase(job.job_type)}</h2><span className={`status-pill status-${job.status}`}>{job.status}</span><p>{job.status_message}</p><div className="progress"><i style={{ width: `${Math.round(job.progress * 100)}%` }} /></div><dl><div><dt>Provider</dt><dd>{job.provider}</dd></div><div><dt>Attempts</dt><dd>{job.attempt_count}</dd></div><div><dt>Created</dt><dd>{formatDate(job.created_at)}</dd></div>{jobRun.data?.workflow_id ? <div><dt>Workflow</dt><dd>{jobRun.data.workflow_id}</dd></div> : null}</dl><h3>Run timeline</h3>{jobRun.isLoading ? <p className="muted">Loading saved stages…</p> : null}{jobRun.error ? <p className="form-error">Run history is unavailable.</p> : null}{jobRun.data ? <ol className="run-timeline">{jobRun.data.stages.map((stage) => <li className={`stage-${stage.state}`} key={stage.key}><i /><div><strong>{stage.label}</strong><small>{stage.detail}</small>{stage.occurred_at ? <time>{formatDate(stage.occurred_at)}</time> : null}</div></li>)}</ol> : null}{jobRun.data?.recovery_message ? <div className="recovery-card"><strong>{titleCase(jobRun.data.recovery_action ?? "Recovery")}</strong><p>{jobRun.data.recovery_message}</p>{jobRun.data.can_retry ? <small>Use ↻ in Background jobs to queue a linked retry.</small> : null}</div> : null}{jobRun.data?.retry_of_job_id ? <p className="muted">Retry of {shortId(jobRun.data.retry_of_job_id)}</p> : null}{jobRun.data?.retried_by_job_id ? <p className="muted">Retried as {shortId(jobRun.data.retried_by_job_id)}</p> : null}{job.error_detail ? <p className="form-error">{job.error_detail}</p> : null}</InspectorSection> : null}
      {asset ? <InspectorSection icon={<Box size={16} />} title="Asset">
        <h2>{assetName(asset)}</h2><div className="inspector-preview"><AssetPreview key={asset.id} asset={asset} /></div>
        <div className="inspector-actions">
          {asset.kind === "image" ? <button className="primary-button" type="button" onClick={() => { useDariusStore.getState().addReferenceAsset(asset.id); useDariusStore.getState().setView("talk"); setInspectorOpen(false); }}>Use with Darius</button> : null}
          <button className="secondary-button" type="button" onClick={() => useDariusStore.getState().setView("map")}><MapIcon size={14} /> Open in Map</button>
          <button className="secondary-button" type="button" onClick={() => useDariusStore.getState().setView("edit")}><Scissors size={14} /> Open in Edit</button>
        </div>
        <dl><div><dt>Role</dt><dd>{titleCase(asset.role)}</dd></div><div><dt>Approval</dt><dd>{titleCase(asset.approval_state)}</dd></div><div><dt>Dimensions</dt><dd>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "—"}</dd></div><div><dt>Duration</dt><dd>{asset.duration ? `${asset.duration.toFixed(2)}s` : "—"}</dd></div><div><dt>Provider</dt><dd>{titleCase(asset.provider)}</dd></div><div><dt>SHA-256</dt><dd className="hash">{asset.content_hash}</dd></div>{asset.parent_asset_ids.length ? <div><dt>Parents</dt><dd>{asset.parent_asset_ids.map(shortId).join(", ")}</dd></div> : null}</dl>
        <h3>Provenance</h3>{provenance.isLoading ? <p className="muted">Loading generation record…</p> : null}{provenance.error ? <p className="form-error">Provenance is not available.</p> : null}
        {provenance.data?.generation ? <><dl><div><dt>Workflow</dt><dd>{provenance.data.generation.workflow_definition_id}</dd></div><div><dt>Prompt</dt><dd>{provenance.data.generation.prompt}</dd></div><div><dt>Model</dt><dd>{provenance.data.generation.model ?? "—"}</dd></div><div><dt>Seed</dt><dd>{provenance.data.generation.seed ?? "—"}</dd></div><div><dt>Sources</dt><dd>{provenance.data.generation.source_asset_ids.map(shortId).join(", ") || "None"}</dd></div></dl><details className="metadata-details"><summary>Provider & generation metadata</summary><pre>{JSON.stringify({ parameters: provenance.data.generation.parameters, provider: provenance.data.generation.provider_response_metadata }, null, 2)}</pre></details></> : null}
        {provenance.data?.import ? <dl><div><dt>Import</dt><dd>{provenance.data.import.original_filename ?? "Uploaded file"}</dd></div><div><dt>SHA-256</dt><dd className="hash">{provenance.data.import.content_hash}</dd></div></dl> : null}
      </InspectorSection> : null}
    </aside>
  );
}

function InspectorSection({ children, icon, title }: { children: React.ReactNode; icon: React.ReactNode; title: string }) {
  return <section className="inspector-section"><span className="inspector-type">{icon}{title}</span>{children}</section>;
}
