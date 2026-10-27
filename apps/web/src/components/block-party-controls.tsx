"use client";

import { useRef, useState } from "react";
import { PackageOpen, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api-client";
import type { BlockPartyReadiness } from "@/lib/types";

export function BlockPartyImport({ onImported, disabled = false }: { onImported: () => Promise<void>; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  async function upload(file?: File) {
    if (!file) return;
    setError(""); setStatus("");
    if (file.size > 64 * 1024 * 1024) { setError("Export without example inputs/models: the ZIP limit is 64 MiB."); return; }
    setBusy(true);
    try {
      const result = await api.importBlockParty(file);
      await onImported();
      setStatus(`${result.name}: ${result.already_imported ? "already imported; existing recipe kept" : "imported"}. Check dependencies, inspect the input map, then choose Use for / Default and save. Nothing was rendered or installed.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not import this Block Party job."); }
    finally { setBusy(false); if (input.current) input.current.value = ""; }
  }
  return <div className="block-party-controls">
    <input ref={input} type="file" accept=".zip,application/zip" aria-label="Block Party job ZIP" hidden disabled={disabled || busy} onChange={(event) => void upload(event.target.files?.[0])} />
    <button type="button" className="secondary-button" disabled={disabled || busy} onClick={() => input.current?.click()}><PackageOpen size={16} />{busy ? "Importing recipe…" : "Import Block Party ZIP"}</button>
    <small>Export one job ZIP from Block Party. Only its API graph and contract are imported; examples, scripts and saved approvals are not used.</small>
    {status ? <p role="status">{status}</p> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </div>;
}

export function BlockPartyCheck({ workflowId }: { workflowId: string }) {
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<BlockPartyReadiness | null>(null);
  const [error, setError] = useState("");
  async function check() {
    setBusy(true); setError(""); setReport(null);
    try { setReport(await api.blockPartyReadiness(workflowId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not check this recipe."); }
    finally { setBusy(false); }
  }
  return <div className="block-party-controls" aria-label="Block Party dependency check">
    <button className="secondary-button" type="button" disabled={busy} onClick={() => void check()}><ShieldCheck size={16} />{busy ? "Verifying files and nodes…" : "Check dependencies"}</button>
    {busy ? <small role="status">Checking local node versions and model hashes. Large models may take a moment; no model is loaded into VRAM.</small> : null}
    {report ? <div role="status" className="block-party-report">
      <strong>{report.ready ? "Declared dependencies verified" : "Preparation needed"}</strong>
      <small>{report.checked.models} models · {report.checked.node_packs} node packs · {report.checked.node_classes} loaded node types</small>
      {report.issues.length ? <ul>{report.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.message}</li>)}</ul> : null}
      {report.warnings.map((warning) => <small key={warning}>{warning}</small>)}
      <small>{report.note}</small>
    </div> : null}
    {error ? <p role="alert" className="form-error">{error}</p> : null}
  </div>;
}
