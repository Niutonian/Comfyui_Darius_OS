"use client";

export type ShotGenerationDraft = { briefId: string; prompt: string; workflowId: string | null; referenceIds: string[]; jobId: string | null };

export function ShotGenerationDrafts({ value, availableIds, onReview, onJob }: {
  value: unknown; availableIds: string[];
  onReview: (draft: ShotGenerationDraft) => void; onJob: (id: string) => void;
}) {
  if (!Array.isArray(value)) return null;
  const drafts: ShotGenerationDraft[] = value.flatMap((item: unknown) => {
    if (!item || typeof item !== "object") return [];
    const row = item as Record<string, unknown>;
    if (typeof row.brief_id !== "string" || typeof row.prompt !== "string") return [];
    return [{ briefId: row.brief_id, prompt: row.prompt,
      workflowId: typeof row.workflow_id === "string" ? row.workflow_id : null,
      referenceIds: Array.isArray(row.reference_asset_ids) ? row.reference_asset_ids.filter((id): id is string => typeof id === "string") : [],
      jobId: typeof row.job_id === "string" ? row.job_id : null }];
  });
  return <section aria-label="Shot generation plan">{drafts.map((draft, index) => <details key={draft.briefId} className="assistant-tool-history">
    <summary>Shot {index + 1} · {draft.jobId ? "Render job saved" : draft.workflowId ? "Ready for review" : "Needs a workflow"}</summary>
    <p>{draft.prompt}</p>
    <small>{draft.referenceIds.length} project reference(s)</small>
    {draft.jobId ? <button className="secondary-button" type="button" onClick={() => onJob(draft.jobId!)}>View shot {index + 1} job</button>
      : <button className="secondary-button" type="button" disabled={!draft.workflowId || !availableIds.includes(draft.workflowId)} onClick={() => onReview(draft)}>Review shot {index + 1}</button>}
  </details>)}</section>;
}
