"use client";

import { useWorkspaceState } from "@/lib/workspace-session";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useWorkflows } from "@/lib/queries";
import type { Asset } from "@/lib/types";
import { ProposalCard, type DraftProposal } from "./talk-view";
import { MediaPreview } from "./media-preview";

export function CloudGeneration({ projectId, assets }: { projectId: string; assets: Asset[] }) {
  const workflows = useWorkflows();
  const models = (workflows.data ?? []).filter((item) => item.execution_provider === "bfl");
  const [modelId, setModelId] = useWorkspaceState(`cloud:${projectId}:model`, "bfl-flux-3-image");
  const [prompt, setPrompt] = useWorkspaceState(`cloud:${projectId}:prompt`, "");
  const [selectedIds, setSelectedIds] = useWorkspaceState<string[]>(`cloud:${projectId}:references`, []);
  const [draft, setDraft] = useWorkspaceState<DraftProposal>(`cloud:${projectId}:draft`, null);
  const connection = useQuery({ queryKey: ["bfl-connection"], queryFn: api.bflConnection, enabled: false, retry: false });
  const workflow = models.find((item) => item.id === modelId);
  const kind = workflow?.required_inputs.some((input) => input.type === "asset:video") ? "video" : "image";
  const needsReferences = workflow?.required_inputs.some((input) => ["images", "keyframes", "video", "start_video", "input_video", "draft_cache"].includes(input.key));
  const needsPrompt = workflow?.required_inputs.some((input) => input.key === "prompt" && input.required);
  const references = assets.filter((item) => item.kind === kind && item.role !== "derivative");
  return <section className="cloud-generation os-window" aria-label="BFL cloud generation">
    <header className="os-chrome"><strong>Black Forest Labs / FLUX 3</strong><button className="secondary-button" type="button" disabled={connection.isFetching} onClick={() => void connection.refetch()}>{connection.isFetching ? "Checking…" : "Check connection"}</button></header>
    <div className="cloud-generation-body">
      <p>Generate and edit images, animate keyframes, continue clips, enhance drafts, edit video, or upscale. This uses BFL’s cloud API—not ComfyUI or your GPU.</p>
      {connection.data ? <p role="status">{!connection.data.configured ? "BFL_API_KEY is missing on the server." : connection.data.authenticated ? connection.data.credits_available ? "API key accepted · credits available." : "API key accepted · add credits in your BFL dashboard." : "BFL authentication failed."}</p> : null}
      {connection.error ? <p className="form-error" role="alert">{connection.error.message}</p> : null}
      {workflows.isError ? <p className="form-error" role="alert">Could not load cloud workflows. Check the backend connection.</p> : null}
      {!workflows.isLoading && !models.length ? <p>Set BFL_API_KEY on the backend and restart it to enable cloud workflows. Keys never appear in this browser.</p> : null}
      <div className="input-stack">
        <label><span>Cloud model / operation</span><select disabled={!models.length || Boolean(draft)} value={modelId} onChange={(event) => setModelId(event.target.value)}>{models.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label><span>{modelId.includes("draft-enhance") ? "Note (optional; the saved draft keeps its original prompt)" : "Visual prompt / edit instruction"}</span><textarea rows={4} disabled={Boolean(draft)} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe the subject, scene, framing, motion and sound you want." /></label>
      </div>
      {needsReferences ? <fieldset className="cloud-reference-list" disabled={Boolean(draft)}><legend>Explicit project references · {kind} · {selectedIds.length}/10 selected</legend>{references.map((asset) => <label className="cloud-reference-card" key={asset.id}><input type="checkbox" checked={selectedIds.includes(asset.id)} disabled={!selectedIds.includes(asset.id) && selectedIds.length >= 10} onChange={(event) => setSelectedIds((current) => event.target.checked ? [...current, asset.id] : current.filter((id) => id !== asset.id))} /><span className="cloud-reference-thumbnail"><MediaPreview asset={asset} compact /></span><span className="cloud-reference-copy"><strong>{String(asset.metadata.display_name ?? asset.metadata.original_filename ?? `${asset.kind} ${asset.id.slice(0, 8)}`)}{asset.metadata.bfl_draft ? " · saved FLUX draft" : ""}</strong><small>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : asset.kind}{asset.duration ? ` · ${asset.duration.toFixed(1)}s` : ""}</small></span></label>)}{!references.length ? <p>Upload an {kind} to this project first, or enter an API URL in the generation settings.</p> : null}</fieldset> : null}
      {!draft ? <button className="primary-button" type="button" disabled={!workflow || (needsPrompt && !prompt.trim())} onClick={() => setDraft({ id: Date.now(), projectId, text: prompt.trim() || workflow!.name, assets: references.filter((item) => selectedIds.includes(item.id)) })}>Review cloud generation</button> : null}
      <small>No cloud generation starts until you create an action plan and choose Approve &amp; queue. Cost estimates exclude taxes and may change with BFL pricing.</small>
      {draft && workflow ? <ProposalCard key={`${draft.id}-${workflow.id}`} draft={draft} workflow={workflow} onDismiss={() => setDraft(null)} /> : null}
    </div>
  </section>;
}
