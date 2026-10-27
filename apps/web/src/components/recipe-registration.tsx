"use client";

import { useState } from "react";
import { api } from "@/lib/api-client";
import { BlockPartyCheck } from "./block-party-controls";
import type { RecipeManifest, Workflow } from "@/lib/types";

export function RecipeRegistration({ workflow }: { workflow: Workflow }) {
  const [manifest, setManifest] = useState<RecipeManifest | null>(null);
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [registeredStatus, setRegisteredStatus] = useState(workflow.registration?.status ?? "not_registered");
  function show(value: RecipeManifest) {
    setManifest(value);
    setRegisteredStatus(value.status);
    setRoles(Object.fromEntries(value.fields.filter((field) => field.editable !== false && field.role !== "system" && field.role !== "negative").map((field) => [field.slot, field.role])));
  }
  async function inspect(force = false) {
    setBusy(true); setError(""); setStatus("");
    try { show(await api.registerRecipe(workflow.id, force)); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not register this base recipe."); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!manifest) return;
    setBusy(true); setError(""); setStatus("");
    try {
      const result = await api.saveRecipeMapping(workflow.id, manifest.source_digest, roles);
      show(result);
      setStatus(result.status === "ready" ? "Input map saved for this base version. No render was submitted." : "Mapping saved, but scene inputs still need attention. Generation remains blocked.");
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save recipe inputs."); }
    finally { setBusy(false); }
  }
  return <div className="recipe-registration" aria-label={`Input registration for ${workflow.name}`}>
    {workflow.id.startsWith("block-party/") ? <BlockPartyCheck workflowId={workflow.id} /> : null}
    <div className="recipe-registration-heading"><button type="button" className="secondary-button" disabled={busy} onClick={() => void inspect()}>{busy ? "Checking recipe…" : manifest ? "Inspect input map" : "Register inputs"}</button>
      <small>{(manifest?.status ?? registeredStatus) === "ready" ? "Input map ready" : (manifest?.status ?? registeredStatus) === "needs_mapping" ? "One-time mapping required" : "Auto-registers on first use"}</small></div>
    {manifest ? <div className="recipe-registration-fields">
      <p>Scene fields receive your image/video description. Preserve fields keep their template text. System and negative instructions are protected. Ambiguous recipes need this setup once per base version.</p>
      {manifest.fields.map((field) => <div className="recipe-registration-field" key={field.slot}>
        <strong>{field.label} <code>{field.slot}</code></strong>
        <small className="recipe-field-value">{field.value ? field.value.slice(0, 300) + (field.value.length > 300 ? "…" : "") : "Empty template text"}</small>
        {field.role === "system" || field.role === "negative" ? <small>{field.role === "system" ? "Protected system instructions" : "Protected negative conditioning"}</small> :
          field.editable === false ? <small>Not exposed by the Block Party author. Re-export to make this input editable.</small> : <label>Input role<select aria-label={`Role for ${workflow.id} ${field.slot}`} disabled={busy} value={roles[field.slot] ?? "unresolved"} onChange={(event) => { setRoles({ ...roles, [field.slot]: event.target.value }); setStatus(""); }}>
            <option value="unresolved">Needs mapping</option><option value="scene">Scene / shot description</option><option value="preserve">Preserve template text</option>
          </select></label>}
      </div>)}
      {!manifest.fields.length ? <small>{manifest.processing_only ? "Image processing recipe: no scene prompt is needed." : "No scene prompt was detected. This recipe cannot generate from text until its input setup is corrected."}</small> : null}
      <div className="recipe-registration-heading"><button type="button" className="secondary-button" disabled={busy} onClick={() => void save()}>Save input map</button><button type="button" className="text-button" disabled={busy} onClick={() => void inspect(true)}>Reinspect base</button><button type="button" className="text-button" disabled={busy} onClick={() => setManifest(null)}>Close input map</button></div>
    </div> : null}
    {status ? <small role="status">{status}</small> : null}
    {error ? <small className="form-error" role="alert">{error}</small> : null}
  </div>;
}
