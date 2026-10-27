"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronRight, Cpu, LoaderCircle, PencilLine, Play, ShieldCheck, Sparkles, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api-client";
import { useDariusStore } from "@/lib/store";
import type { ActionPlan, Asset, Workflow } from "@/lib/types";
import { buildWorkflowInputs, primaryPromptInput, titleCase } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "./states";
import type { DariusMood } from "@/lib/types";
import { LiquidOrb } from "./liquid-orb";
import { ConversationRender } from "./conversation-render";
import { WorkflowRenderPreview } from "./workflow-render-preview";
import { WorkflowJsonInput } from "./workflow-json-input";

export type DraftProposal = { id: number; text: string; assets: Asset[]; projectId: string | null; sourceMessageId?: string } | null;

export function ProposalCard({ draft, workflow, onDismiss }: { draft: NonNullable<DraftProposal>; workflow: Workflow; onDismiss: () => void }) {
  const { activeProjectId, rememberJob } = useDariusStore();
  const [inputs, setInputs] = useState<Record<string, unknown>>(() => buildWorkflowInputs(workflow, draft.text, draft.assets.map((asset) => asset.id)));
  const [plan, setPlan] = useState<ActionPlan | null>(null);
  const [invalidJson, setInvalidJson] = useState<Record<string, boolean>>({});
  const cloud = workflow.execution_provider === "bfl";
  const settingsPanel = useRef<HTMLDetailsElement>(null);
  const options = useQuery({ queryKey: ["workflow-input-options", workflow.id], queryFn: () => api.workflowInputOptions(workflow.id), staleTime: 30_000, retry: false });
  const proposalMutation = useMutation({
    mutationFn: () => api.proposeWorkflow(workflow.id, {
      project_id: activeProjectId!, request_text: draft.text, inputs,
      ...(draft.sourceMessageId ? { source_message_id: draft.sourceMessageId } : {}),
    }),
    onSuccess: (saved) => { setInputs(saved.inputs); setPlan(saved); },
  });
  const approvalMutation = useMutation({
    mutationFn: async () => {
      const approved = await api.approveActionPlan(plan!.id);
      if (!approved.job_id) throw new ApiError("The approved action plan did not create a job.", 500);
      return api.job(approved.job_id);
    },
    onSuccess: rememberJob,
  });
  const missing = Object.values(invalidJson).some(Boolean) || workflow.required_inputs.some((input) => input.required && (inputs[input.key] === undefined || inputs[input.key] === ""));
  const locked = Boolean(plan) || proposalMutation.isPending || approvalMutation.isPending;
  const sameProject = Boolean(activeProjectId && draft.projectId === activeProjectId);
  const inspection = useQuery({
    queryKey: ["render-input-preview", activeProjectId, workflow.id, draft.text, inputs],
    queryFn: () => api.previewWorkflow(workflow.id, { project_id: activeProjectId!, request_text: draft.text, inputs }),
    enabled: sameProject && !missing && !plan,
    retry: false,
  });
  const renderPreview = plan?.expected_output.render_preview ?? inspection.data;
  const previewReady = sameProject && Boolean(renderPreview) && !renderPreview?.blocked && (Boolean(plan) || (!inspection.isFetching && !inspection.isError));
  const actionError = proposalMutation.error ?? approvalMutation.error;

  return (
    <article className="proposal-card">
      <div className="proposal-topline"><span><Sparkles size={15} /> Proposed generation</span><button aria-label="Dismiss proposal" className="icon-button" onClick={onDismiss} type="button"><X size={16} /></button></div>
      <h2>{workflow.name}</h2>
      {cloud ? <p className="muted">Paid BFL API request. Your prompt and selected media leave this PC only after you approve. Local auto-render permission does not apply.</p> : null}
      <details className="proposal-direction"><summary>Creative direction</summary><p className="proposal-request">{draft.text}</p></details>
      <WorkflowRenderPreview preview={renderPreview} loading={!plan && inspection.isFetching} error={inspection.error} onRetry={() => void inspection.refetch()} />
      {!sameProject ? <p className="form-error" role="alert">This draft belongs to another project. Reopen it in its original project.</p> : null}
      <div className="plan-meta">
        <span><Cpu size={14} /> {titleCase(workflow.execution_provider)}</span>
        <span>{titleCase(workflow.output.kind)} × {workflow.output.count}</span>
        {workflow.estimated_vram_gb ? <span>{workflow.estimated_vram_gb} GB VRAM</span> : null}
        <span><ShieldCheck size={14} /> Explicit approval</span>
      </div>
      <details className="proposal-settings" ref={settingsPanel} open={missing || undefined}>
      <summary><span>Generation settings</span><small>{missing ? "Required inputs need attention" : `${workflow.required_inputs.length} settings · ready to review`}</small></summary>
      <div className="proposal-options-status"><small>{options.isFetching ? "Loading model options…" : options.isError ? "Options unavailable. Manual editing is available." : cloud ? "Options from BFL’s published API schema" : "Options from your ComfyUI installation"}</small><button className="secondary-button" type="button" disabled={options.isFetching} onClick={() => void options.refetch()}>Refresh options</button></div>
      <div className="input-stack proposal-inputs">
        {workflow.required_inputs.map((input) => (
          <label key={input.key}>
            <span>{workflow.id.startsWith("assistant-") ? titleCase((input.description.split("·").at(-1) ?? input.key).trim().replace(/^\d+\./, "").replaceAll("_", "-")) : titleCase(input.key.replaceAll("_", "-"))}{input.required ? " *" : ""}</span>
            {options.data?.[input.key]?.length ? (
              <select disabled={locked} value={String(inputs[input.key] ?? "")} onChange={(event) => { setInvalidJson((current) => ({ ...current, [input.key]: false })); setInputs((current) => ({ ...current, [input.key]: options.data![input.key].find((value) => String(value) === event.target.value) ?? event.target.value })); }}>
                {!options.data[input.key].some((value) => String(value) === String(inputs[input.key] ?? "")) ? <option value={String(inputs[input.key] ?? "")}>{inputs[input.key] ? `${String(inputs[input.key])} (current · unavailable)` : "Choose an option"}</option> : null}
                {options.data[input.key].map((value) => <option key={String(value)} value={String(value)}>{String(value)}</option>)}
              </select>
            ) : input.type === "json" ? (
              <WorkflowJsonInput value={inputs[input.key]} disabled={locked} onChange={(value) => setInputs((current) => ({ ...current, [input.key]: value }))} onInvalid={(invalid) => setInvalidJson((current) => ({ ...current, [input.key]: invalid }))} />
            ) : input.type === "string" ? (
              <textarea
                disabled={locked}
                onChange={(event) => setInputs((current) => ({ ...current, [input.key]: event.target.value }))}
                rows={input.key === primaryPromptInput(workflow)?.key ? 4 : 2}
                value={String(inputs[input.key] ?? "")}
              />
            ) : input.type === "asset:image" || input.type === "asset:video" ? (
              <select disabled={locked} onChange={(event) => setInputs((current) => ({ ...current, [input.key]: event.target.value }))} value={String(inputs[input.key] ?? "")}>
                <option value="">Choose an uploaded {input.type.split(":")[1]}</option>
                {cloud && inputs[input.key] && !draft.assets.some((asset) => asset.id === inputs[input.key]) ? <option value={String(inputs[input.key])}>Explicit API reference</option> : null}
                {draft.assets.filter((asset) => asset.kind === input.type.split(":")[1]).map((asset) => <option key={asset.id} value={asset.id}>{asset.kind} · {asset.id.slice(0, 8)}</option>)}
              </select>
            ) : input.type === "boolean" ? (
              <input checked={Boolean(inputs[input.key])} disabled={locked} onChange={(event) => setInputs((current) => ({ ...current, [input.key]: event.target.checked }))} type="checkbox" />
            ) : (
              <input
                disabled={locked}
                max={input.maximum ?? undefined}
                min={input.minimum ?? undefined}
                onChange={(event) => setInputs((current) => ({ ...current, [input.key]: Number(event.target.value) }))}
                type="number"
                value={String(inputs[input.key] ?? "")}
              />
            )}
            {cloud && input.type === "asset:video" ? <><small>Or supply an explicit public API URL / base64 value</small><input aria-label={`${input.key} API URL or base64`} disabled={locked} type="text" value={draft.assets.some((asset) => asset.id === inputs[input.key]) ? "" : String(inputs[input.key] ?? "")} onChange={(event) => setInputs((current) => ({ ...current, [input.key]: event.target.value }))} /></> : null}
            {input.description && !workflow.id.startsWith("assistant-") ? <small>{input.description}</small> : null}
          </label>
        ))}
      </div>
      </details>
      {draft.assets.length ? <details className="proposal-direction"><summary>{draft.assets.length} reference {draft.assets.length === 1 ? "file" : "files"}</summary><div className="plan-attachments">{draft.assets.map((asset) => <span key={asset.id}>{titleCase(asset.kind)} · {asset.id.slice(0, 8)}</span>)}</div></details> : null}
      {plan ? <div className="persisted-plan" role="status"><span><small>Action plan</small><strong>{plan.id.slice(0, 12)}</strong></span><span><small>State</small><strong>{titleCase(plan.state)}</strong></span><span><small>Provider</small><strong>{titleCase(plan.provider)}</strong></span><span><small>Estimated cost</small><strong>{plan.estimated_cost === null ? cloud ? "Billed by BFL · price not estimated" : "Local / unmetered" : `$${plan.estimated_cost.toFixed(2)}`}</strong></span></div> : null}
      {actionError ? <p className="form-error" role="alert">{actionError instanceof ApiError ? actionError.message : "The action plan could not be updated."}</p> : null}
      {approvalMutation.data ? <ConversationRender jobId={approvalMutation.data.id} projectId={activeProjectId} /> : null}
      <div className="proposal-actions">
        {!approvalMutation.isSuccess ? <button className="secondary-button" onClick={() => { setPlan(null); if (settingsPanel.current) settingsPanel.current.open = true; }} type="button"><PencilLine size={15} /> {plan ? "Revise settings" : "Edit settings"}</button> : null}
        {!plan ? <button className="primary-button" disabled={missing || !previewReady || proposalMutation.isPending} onClick={() => proposalMutation.mutate()} type="button">{proposalMutation.isPending ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />} Create action plan</button> : <button className="primary-button" disabled={!previewReady || approvalMutation.isPending || approvalMutation.isSuccess} onClick={() => approvalMutation.mutate()} type="button">{approvalMutation.isPending ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />} {approvalMutation.isSuccess ? "Queued" : "Approve & queue"}</button>}
      </div>
    </article>
  );
}

export function TalkView({
  draft,
  workflows,
  workflowsError,
  workflowsLoading,
  onDismiss,
  onRetry,
  selectedWorkflowId,
  setSelectedWorkflowId,
  mood = "idle",
}: {
  draft: DraftProposal;
  workflows: Workflow[];
  workflowsError: Error | null;
  workflowsLoading: boolean;
  onDismiss: () => void;
  onRetry: () => void;
  selectedWorkflowId: string | null;
  setSelectedWorkflowId: (id: string) => void;
  mood?: DariusMood;
}) {
  const activeProjectId = useDariusStore((state) => state.activeProjectId);
  const [controlMode, setControlMode] = useState<"guided" | "full">("guided");
  const workflow = useMemo(() => selectedWorkflowId ? workflows.find((item) => item.id === selectedWorkflowId) : workflows[0], [selectedWorkflowId, workflows]);

  return (
    <div className={`view talk-view ${!draft && controlMode === "guided" ? "talk-welcome" : ""}`}>
      <header className="view-heading generation-heading">
        <h1 className="sr-only">Create with Darius</h1>
        <div className="segmented" aria-label="Generation control level">
          <button className={controlMode === "guided" ? "active" : ""} onClick={() => setControlMode("guided")} type="button">Generation</button>
          <button className={controlMode === "full" ? "active" : ""} onClick={() => setControlMode("full")} type="button">Workflows</button>
        </div>
      </header>

      {!draft && controlMode === "guided" ? <div className={`presence mood-${mood}`} aria-hidden="true"><LiquidOrb mood={mood} /><span className="presence-caption">{mood === "thinking" ? "DARIUS IS THINKING" : mood === "listening" ? "LISTENING" : mood === "speaking" ? "SPEAKING" : "ROOM FOR YOUR IMAGINATION"}</span></div> : null}
      {!activeProjectId ? <div className="welcome-start"><p>Every story deserves a space of its own.</p><button className="primary-button" onClick={() => document.querySelector<HTMLButtonElement>(".project-trigger")?.click()} type="button">Create or choose a project <ChevronRight size={16} /></button></div> : null}
      {activeProjectId && workflowsLoading ? <LoadingState label="Discovering registered workflows…" /> : null}
      {activeProjectId && workflowsError ? <ErrorState message={workflowsError.message} onRetry={onRetry} /> : null}
      {activeProjectId && !workflowsLoading && !workflowsError && !workflows.length ? <EmptyState title="No workflows registered" description="Enable a workflow contract in the local Darius API to create a generation plan." /> : null}
      {activeProjectId && selectedWorkflowId && !workflow && !workflowsLoading && !workflowsError && workflows.length ? <div role="alert"><p>The selected workflow is unavailable. No alternative has been selected automatically.</p><button className="secondary-button" type="button" onClick={() => setSelectedWorkflowId(workflows[0].id)}>Choose {workflows[0].name}</button></div> : null}
      {activeProjectId && workflow && (controlMode === "full" || draft) ? (
        <>
          {controlMode === "full" ? <section aria-label="Available creative actions" className="action-grid">
            {workflows.map((item) => (
              <button aria-pressed={item.id === workflow.id} className={`action-card ${item.id === workflow.id ? "selected" : ""}`} key={item.id} onClick={() => { setSelectedWorkflowId(item.id); document.querySelector<HTMLTextAreaElement>(".composer textarea")?.focus(); }} type="button">
                <span className="action-icon"><Sparkles /></span>
                <span><small>{titleCase(item.capability)}</small><strong>{item.name}</strong><em>{titleCase(item.execution_provider)} · {titleCase(item.output.kind)}</em></span>
                <ChevronRight size={18} />
              </button>
            ))}
          </section> : null}
          {draft ? <ProposalCard draft={draft} key={`${draft.id}-${workflow.id}`} onDismiss={onDismiss} workflow={workflow} /> : (
            <p className="welcome-note">Talk through an idea or ask Darius to create something. You’ll review any generation before it runs.</p>
          )}
        </>
      ) : null}

      {activeProjectId && workflow && controlMode === "full" ? (
        <section className="full-control">
          <div><span className="eyebrow">Your generation tools</span><h2>{workflow.name}</h2><p>Explore the inputs and output of your registered workflow.</p></div>
          <label className="workflow-picker">Workflow<select value={workflow.id} onChange={(event) => setSelectedWorkflowId(event.target.value)}>{workflows.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <dl>
            <div><dt>Provider</dt><dd>{titleCase(workflow.execution_provider)}</dd></div>
            <div><dt>Capability</dt><dd>{titleCase(workflow.capability)}</dd></div>
            <div><dt>Version</dt><dd>{workflow.version}</dd></div>
            <div><dt>Approval</dt><dd>{workflow.requires_approval ? "Required" : "Automatic"}</dd></div>
          </dl>
          <h3>Semantic inputs</h3>
          {workflow.required_inputs.map((input) => <div className="contract-row" key={input.key}><code>{input.key}</code><span>{input.type}</span><span>{input.required ? "Required" : "Optional"}</span></div>)}
        </section>
      ) : null}
    </div>
  );
}
