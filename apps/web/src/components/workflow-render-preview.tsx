"use client";

import type { RenderPreview } from "@/lib/types";

export function WorkflowRenderPreview({ preview, loading, error, onRetry }: {
  preview?: RenderPreview; loading: boolean; error: Error | null; onRetry: () => void;
}) {
  return <details className="render-input-preview" open>
    <summary>Actual render inputs</summary>
    {loading ? <p role="status">Inspecting final workflow inputs…</p> : null}
    {error ? <div role="alert"><p>Could not verify render inputs: {error.message}</p><button className="secondary-button" type="button" onClick={onRetry}>Retry input inspection</button></div> : null}
    {preview ? <>
      <small>{preview.verification === "graph" ? "Compiled graph · includes your current settings" : "Contract inputs · final provider graph not verified"}</small>
      <p>Workflow: {preview.origin_workflow_id ?? preview.workflow_id}</p>
      {preview.canvases?.map((canvas) => <p key={canvas.node_id}>Image canvas: {canvas.width} × {canvas.height}</p>)}
      {([ ["Positive prompt", preview.positive], ["Negative prompt", preview.negative], ["Models", preview.models], ["Graph image inputs", preview.image_inputs] ] as const).map(([label, entries]) => <section key={label} aria-label={label}>
        <h3>{label}</h3>
        {entries.length ? entries.map((item, index) => <div key={`${item.slot}-${index}`}><small>{item.label}{item.slot ? ` · ${item.slot}` : ""}</small><p>{item.value || "Empty"}</p></div>) : <p>None found</p>}
      </section>)}
      <section aria-label="Project references"><h3>Project references</h3><p>{preview.reference_asset_ids.length ? preview.reference_asset_ids.join(", ") : "No recorded project references"}</p></section>
      {preview.warnings.length ? <div className="render-input-warnings" role={preview.blocked ? "alert" : "status"}>{preview.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div> : null}
      {preview.blocked ? <strong>Rendering blocked. Revise the workflow inputs first.</strong> : null}
    </> : null}
  </details>;
}
