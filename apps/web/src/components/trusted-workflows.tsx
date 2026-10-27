"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { RecipeRegistration } from "./recipe-registration";
import { BlockPartyImport } from "./block-party-controls";
import { api } from "@/lib/api-client";
import type { TrustedWorkflowPreferences, Workflow, WorkflowPurpose } from "@/lib/types";
import { readWorkspaceValue, useWorkspaceState } from "@/lib/workspace-session";

const purposes: [WorkflowPurpose, string][] = [
  ["text-to-image", "Generate image"], ["image-to-image", "Edit image / img2img"],
  ["image-upscale", "Upscale image"], ["text-to-video", "Generate video"],
  ["image-to-video", "Animate image"], ["video-to-video", "Edit video"],
  ["character-sheet", "Character sheet"], ["face-consistency", "Face consistency"], ["lip-sync", "Lip sync"],
];

function supportsPurpose(workflow: Workflow, purpose: WorkflowPurpose) {
  if (workflow.assignable_purposes) return workflow.assignable_purposes.includes(purpose);
  if (purpose === "character-sheet") return workflow.output.kind === "image" && (workflow.capability === "text-to-image" || workflow.capability === "character-sheet");
  if (purpose === "face-consistency") return workflow.output.kind === "image" && (workflow.capability === "image-to-image" || workflow.capability === "face-consistency");
  return purpose === workflow.capability || (purpose === "image-upscale" && workflow.execution_provider === "local-comfyui" && workflow.output.kind === "image" && (workflow.capability === "image-to-image" || workflow.required_inputs.some((input) => input.type === "asset:image")));
}

export function TrustedWorkflows({ projectId, scope = "project", onStateChange }: { projectId?: string; scope?: "project" | "global"; onStateChange?: (state: { dirty: boolean; error: string }) => void }) {
  const isGlobal = scope === "global";
  const cacheKey = `workflow-preferences:${isGlobal ? "global" : projectId}`;
  const [value, setValue] = useWorkspaceState<TrustedWorkflowPreferences | null>(`${cacheKey}:value`, null);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [query, setQuery] = useState("");
  const [task, setTask] = useState<WorkflowPurpose | "all">("all");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [folder, setFolder] = useState("");
  const [dirty, setDirty] = useWorkspaceState(`${cacheKey}:dirty`, false);
  const [reload, setReload] = useState(0);
  const [globalDefaults, setGlobalDefaults] = useState<TrustedWorkflowPreferences["global_defaults"]>({ enabled: false, entries: [] });
  useEffect(() => { onStateChange?.({ dirty, error }); }, [dirty, error, onStateChange]);
  useEffect(() => {
    let cancelled = false;
    const load = isGlobal ? api.globalWorkflowDefaults() : projectId ? api.trustedWorkflows(projectId) : Promise.reject(new Error("Choose a project to configure overrides."));
    void Promise.all([load, api.workflowRecipes()]).then(([saved, available]) => {
      if (!cancelled) { setError(""); if (!readWorkspaceValue(`${cacheKey}:dirty`)) { setValue(saved); setDirty(false); } setGlobalDefaults(saved.global_defaults ?? { enabled: false, entries: [] }); setWorkflows(available.workflows); setFolder(available.folder); }
    }).catch((err: Error) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [projectId, reload, isGlobal, cacheKey, setDirty, setValue]);
  useEffect(() => {
    if (isGlobal) return;
    const update = (event: Event) => { const detail = (event as CustomEvent<TrustedWorkflowPreferences>).detail; if (detail) setGlobalDefaults(detail); };
    window.addEventListener("darius-global-workflows-saved", update);
    return () => window.removeEventListener("darius-global-workflows-saved", update);
  }, [isGlobal]);
  function change(next: TrustedWorkflowPreferences) { setValue(next); setDirty(true); setStatus(""); }
  async function refresh() {
    setRefreshing(true); setError(""); setStatus("");
    try {
      const catalog = await api.refreshWorkflowRecipes();
      setWorkflows(catalog.workflows); setFolder(catalog.folder);
      setStatus(`Found ${catalog.workflows.length} reusable recipes. Choose a task, trust its recipe, select Default, and save. Unsaved selections were kept; nothing was rendered.`);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not refresh workflow folder."); }
    finally { setRefreshing(false); }
  }
  async function save() {
    if (!value || (!isGlobal && !projectId)) return; setSaving(true); setError("");
    try {
      const result = isGlobal ? await api.saveGlobalWorkflowDefaults(value) : await api.saveTrustedWorkflows(projectId!, value);
      setValue(result); if (result.global_defaults) setGlobalDefaults(result.global_defaults);
      if (isGlobal) window.dispatchEvent(new CustomEvent("darius-global-workflows-saved", { detail: result }));
      setDirty(false); setStatus(isGlobal ? "Global defaults saved. All projects inherit these actions unless overridden." : "Project overrides saved. Other actions inherit enabled global defaults. Applies to new requests in chat and voice.");
    }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save trusted workflows."); }
    finally { setSaving(false); }
  }
  const known = new Set(workflows.map((workflow) => workflow.id));
  const missing = value?.entries.filter((entry) => !known.has(entry.workflow_id)) ?? [];
  const inherited = !isGlobal && globalDefaults?.enabled ? globalDefaults.entries.filter((entry) => !value?.enabled || !value.entries.some((override) => override.purpose === entry.purpose)) : [];
  const filtered = workflows.filter((workflow) => (task === "all" || supportsPurpose(workflow, task)) && `${workflow.name} ${workflow.id} ${workflow.capability}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="trusted-workflows" aria-label={isGlobal ? "Global workflow defaults" : "Trusted workflows"}>
    <h2>{isGlobal ? "Global workflow defaults" : "Project workflow overrides"}</h2>
    <p>{isGlobal ? "Choose reusable defaults for every project on this Darius server. Explicit workflow choices and project action overrides take precedence." : "Override individual actions for this project. Actions without a project mapping inherit the enabled global defaults configured in Settings."} Validation, reference ownership, and render approvals still apply.</p>
    {!isGlobal ? <div className="trusted-workflow-inheritance">
      <small>Priority: explicit workflow choice → project action override → global default. With both scopes disabled, use compatible bases from the default folder.</small>
      {inherited.length ? <><p>Inherited global recipes</p><ul>{inherited.map((entry) => <li key={`${entry.workflow_id}:${entry.purpose}`}>{purposes.find(([purpose]) => purpose === entry.purpose)?.[1]}: {workflows.find((workflow) => workflow.id === entry.workflow_id)?.name ?? entry.workflow_id}{entry.is_default ? " · default" : ""}{!known.has(entry.workflow_id) ? " · unavailable, refresh or replace globally" : ""}</li>)}</ul></> : <small>{globalDefaults?.enabled ? "All configured global actions are overridden here." : "No enabled global defaults. Configure them in Settings."}</small>}
    </div> : null}
    <button className="secondary-button" type="button" disabled={saving || refreshing} onClick={() => void refresh()}><RefreshCw size={14} className={refreshing ? "spin" : undefined} />{refreshing ? "Refreshing…" : "Refresh workflows"}</button>
    <BlockPartyImport disabled={saving || refreshing} onImported={async () => {
      const catalog = await api.workflowRecipes();
      setWorkflows(catalog.workflows); setFolder(catalog.folder);
    }} />
    <p className="trusted-workflow-folder">Base folder: <code>{folder || "Not configured"}</code>. New JSON files appear after refresh. Generated image/video drafts are not base recipes.</p>
    {error ? <div role="alert" className="form-error">{error}{!value ? <button className="secondary-button" type="button" onClick={() => setReload((count) => count + 1)}>Retry loading</button> : null}</div> : null}
    {!value && !error ? <p role="status">Loading workflows…</p> : null}
    {value ? <fieldset disabled={saving || refreshing}>
      <label className="trusted-workflow-switch"><input type="checkbox" checked={value.enabled} onChange={(event) => change({ ...value, enabled: event.target.checked })} />{isGlobal ? "Use global workflow defaults" : "Use project workflow overrides"}</label>
      <small>{isGlobal ? "These mappings apply across existing and new projects. Disabling them keeps saved choices but stops global inheritance." : "Disabling project overrides keeps your saved choices and uses enabled global defaults instead."} Generated drafts are never automatic base recipes.</small>
      <label className="trusted-workflow-search">Task type<select aria-label="Workflow task type" value={task} onChange={(event) => setTask(event.target.value as WorkflowPurpose | "all")}>
        <option value="all">All workflow types · {workflows.length}</option>
        {purposes.map(([purpose, label]) => <option key={purpose} value={purpose}>{label} · {workflows.filter((workflow) => supportsPurpose(workflow, purpose)).length} available</option>)}
      </select></label>
      <small>Choose a task to find matching recipes. Local video bases can be assigned to generation, animation, or editing. Assignment controls routing; actual inputs and installed nodes are checked before rendering.</small>
      <label className="trusted-workflow-search">Find a workflow<input aria-label="Search trusted workflow catalog" placeholder="Name, capability, or ID" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <p>{value.entries.length} trusted · {workflows.length} available in this project</p>
      <div className="trusted-workflow-list">
        {filtered.map((workflow) => {
          const entry = value.entries.find((item) => item.workflow_id === workflow.id);
          return <div className={entry ? "trusted-workflow-row selected" : "trusted-workflow-row"} key={workflow.id}>
            <label className="trusted-workflow-choice"><input type="checkbox" checked={Boolean(entry)} aria-label={`Trust ${workflow.name}`} onChange={(event) => {
              if (!event.target.checked) { change({ ...value, entries: value.entries.filter((item) => item.workflow_id !== workflow.id) }); return; }
              const purpose = task !== "all" && supportsPurpose(workflow, task) ? task : workflow.capability;
              change({ ...value, entries: [...value.entries, { workflow_id: workflow.id, purpose, is_default: !value.entries.some((item) => item.purpose === purpose && item.is_default) }] });
            }} /><span><strong>{workflow.name}</strong><small>{workflow.capability} · {workflow.execution_provider} · v{workflow.version}</small><small>{workflow.id}</small></span></label>
            {entry ? <div className="trusted-workflow-options">
              <label>Use for<select aria-label={`Purpose for ${workflow.name}`} value={entry.purpose} onChange={(event) => {
                const purpose = event.target.value as WorkflowPurpose;
                change({ ...value, entries: value.entries.map((item) => item === entry ? { ...item, purpose, is_default: !value.entries.some((other) => other !== entry && other.purpose === purpose && other.is_default) } : item) });
              }}>{purposes.filter(([purpose]) => supportsPurpose(workflow, purpose) || purpose === entry.purpose).map(([purpose, label]) => <option key={purpose} value={purpose}>{label}</option>)}</select></label>
              <label><input type="radio" name={`${scope}-trusted-default-${entry.purpose}`} checked={entry.is_default} aria-label={`Default ${entry.purpose}: ${workflow.name}`} onChange={() => change({ ...value, entries: value.entries.map((item) => item.purpose === entry.purpose ? { ...item, is_default: item.workflow_id === workflow.id } : item) })} />Default</label>
              {workflow.assignable_purposes && workflow.output.kind === "video" ? <small className="trusted-workflow-action-note">Routing label, not a verified mode. Detected possible {workflow.input_hints?.image && workflow.input_hints?.video ? "image and video" : workflow.input_hints?.video ? "video" : workflow.input_hints?.image ? "image" : "text"} inputs; optional branches and required references are confirmed during inspection.</small> : null}
            </div> : null}
            {workflow.execution_provider === "local-comfyui" && workflow.version === "folder" ? <RecipeRegistration workflow={workflow} /> : null}
          </div>;
        })}
        {!filtered.length ? <p>{task === "all" ? "No matching workflows." : `No matching ${purposes.find(([purpose]) => purpose === task)?.[1].toLowerCase()} recipes in this project.`} A compatible workflow must be registered in Darius before it can be trusted. Existing image recipes are not converted into video workflows.</p> : null}
      </div>
      {missing.map((entry) => <div className="trusted-workflow-row" key={entry.workflow_id}><span>Unavailable: {entry.workflow_id}</span><button type="button" className="secondary-button" onClick={() => change({ ...value, entries: value.entries.filter((item) => item !== entry) })}>Remove unavailable recipe</button></div>)}
      <button type="button" className="primary-button" disabled={!dirty} onClick={() => void save()}>{saving ? "Saving…" : isGlobal ? "Save global defaults" : "Save trusted workflows"}</button>
      {dirty ? <small>Unsaved changes</small> : null}
    </fieldset> : null}
    {status ? <p role="status">{status}</p> : null}
  </section>;
}
