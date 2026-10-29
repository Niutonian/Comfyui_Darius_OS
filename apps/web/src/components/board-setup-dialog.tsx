"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Download, RefreshCw, X } from "lucide-react";
import { api, ApiError } from "@/lib/api-client";
import { boardSetupApi, subscribeBoardSetup, type BoardSetup, type BoardSetupRequest } from "@/lib/board-setup";
import { canvasProfiles, type CanvasProfile } from "@/lib/canvas-profile";

import { ReadinessSummary } from "./readiness-summary";
import { useDariusStore } from "@/lib/store";
import { rememberWorkspaceValue } from "@/lib/workspace-session";
import type { Health } from "@/lib/types";
import type { ComfyConnection } from "@/lib/board-setup";

const bytes = (value: number) => value >= 1e9 ? `${(value / 1e9).toFixed(1)} GB` : `${Math.ceil(value / 1e6)} MB`;

export function BoardSetupDialog() {
  const [pending, setPending] = useState<BoardSetupRequest | null>(null);
  const active = useRef<BoardSetupRequest | null>(null);
  const [status, setStatus] = useState<BoardSetup | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [connection, setConnection] = useState<ComfyConnection | null>(null);
  const [error, setError] = useState("");
  const [restart, setRestart] = useState(true);
  const [working, setWorking] = useState(false);
  const [comfyFolder, setComfyFolder] = useState('');
  const [comfyOutput, setComfyOutput] = useState('');
  const [comfyUrl, setComfyUrl] = useState('http://127.0.0.1:8188');
  const [connectionNotice, setConnectionNotice] = useState('');
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => subscribeBoardSetup(value => {
    if (active.current) { value.reject(new ApiError("Another board is being prepared. Finish or close its setup first.", 409)); return; }
    active.current = value;
    setPending(value); setStatus(null); setHealth(null); setConnection(null); setError(""); setRestart(true); setWorking(false); setConnectionNotice('');
  }), []);
  useEffect(() => {
    if (!pending) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    void api.health().then(value => { if (!cancelled) setHealth(value); }).catch(() => { if (!cancelled) setHealth({ status: "offline", components: {} }); });
    void boardSetupApi.connection().then(value => {
      if (!cancelled) { setConnection(value); setComfyFolder(value.root); setComfyUrl(value.baseUrl); setComfyOutput(value.outputDir ?? ''); }
    }).catch(() => { /* Connection controls remain available for manual repair. */ });
    async function refresh(initial: boolean) {
      try {
        const value = initial ? await boardSetupApi.check(pending!.profile) : await boardSetupApi.status(pending!.profile);
        if (cancelled) return;
        setStatus(value);
      } catch (value) { if (!cancelled) setError(value instanceof Error ? value.message : "Could not check board setup."); }
      if (!cancelled) timer = setTimeout(() => void refresh(false), 1500);
    }
    void refresh(true);
    panel.current?.focus();
    return () => { cancelled = true; clearTimeout(timer); previous?.focus(); };
  }, [pending]);
  useEffect(() => () => { active.current?.reject(new ApiError("Board setup closed. Your draft is saved; retry Generate to continue.", 409)); active.current = null; }, []);
  function close() {
    active.current?.reject(new ApiError("Board setup closed. Your draft is saved; retry Generate to continue.", 409));
    active.current = null; setPending(null);
  }
  async function action(prepare: boolean) {
    if (!pending) return;
    setWorking(true); setError("");
    try {
      const value = prepare && status?.planDigest ? await boardSetupApi.prepare(pending.profile, status.planDigest, restart) : await boardSetupApi.check(pending.profile);
      if (active.current === pending) setStatus(value);
    } catch (value) { if (active.current === pending) setError(value instanceof Error ? value.message : "Could not prepare this board."); }
    finally { if (active.current === pending) setWorking(false); }
  }
  async function connectionAction(detect: boolean) {
    if (!pending) return;
    setWorking(true); setError(''); setConnectionNotice('');
    try {
      const value = detect ? await boardSetupApi.detect(comfyUrl) : await boardSetupApi.connect(comfyFolder, comfyUrl, comfyOutput);
      if (active.current !== pending) return;
      setConnection(value); setComfyFolder(value.root); setComfyUrl(value.baseUrl); setComfyOutput(value.outputDir ?? '');
      setConnectionNotice(detect ? 'Found ComfyUI. Save this connection to use it.' : 'Connected. Checking this board again…');
      if (!detect) setStatus(await boardSetupApi.check(pending.profile));
    } catch (value) { if (active.current === pending) setError(value instanceof Error ? value.message : 'Could not connect ComfyUI.'); }
    finally { if (active.current === pending) setWorking(false); }
  }
  if (!pending) return null;
  const actions = status?.actions ?? [];
  const total = actions.reduce((sum, item) => sum + (item.size_bytes ?? 0), 0);
  const busy = working || !status || status.state === "checking" || status.state === "preparing";
  const progress = status?.progress;
  return createPortal(<div className="board-setup-backdrop" onKeyDown={event => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
    if (event.key === "Tab" && panel.current) {
      const nodes = [...panel.current.querySelectorAll<HTMLElement>("button:not(:disabled),input:not(:disabled),a[href]")];
      const first = nodes[0], last = nodes.at(-1);
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }}><div ref={panel} role="dialog" aria-modal="true" aria-labelledby="board-setup-title" tabIndex={-1} className="board-setup-panel">
    <header><div><span className="eyebrow">First-use preparation · Block Party</span><h2 id="board-setup-title">Prepare {canvasProfiles[pending.profile as CanvasProfile]?.name ?? "this board"}</h2></div><button className="icon-button" aria-label="Close board preparation" onClick={close}><X size={20}/></button></header>
    <ReadinessSummary health={health} setup={status} connection={connection} onAction={action => {
      if (action === "connection") { const details = document.getElementById("board-setup-connection") as HTMLDetailsElement | null; if (details) { details.open = true; details.scrollIntoView?.({ block: "nearest" }); } }
      else if (action === "dependencies") document.getElementById("board-setup-dependencies")?.scrollIntoView?.({ block: "nearest" });
      else { rememberWorkspaceValue("settings:category", action); useDariusStore.getState().setView("settings"); close(); }
    }} />
    <p>Models and node packs are installed once in your ComfyUI and shared by your boards. Existing files and node revisions are checked before anything changes.</p>
    <div role="status" aria-live="polite" id="board-setup-dependencies" className="board-setup-status"><RefreshCw size={18} className={busy ? "board-setup-spinning" : ""}/><span>{progress?.message ?? status?.message ?? "Checking this board’s dependencies…"}</span></div>
    {progress?.bytes_total ? <><progress aria-label="Model download" max={progress.bytes_total} value={progress.bytes_done ?? 0}/><small>{bytes(progress.bytes_done ?? 0)} / {bytes(progress.bytes_total)}{progress.speed ? ` · ${bytes(progress.speed)}/s` : ""}</small></> : null}
    {actions.length ? <><strong>{total ? `${bytes(total)} of model downloads` : "Dependencies to prepare"}{actions.some(item => item.kind === "node") ? " · custom nodes included" : ""}</strong><ul className="board-setup-list">{actions.map((item, index) => <li key={`${item.filename ?? item.name}:${index}`}><span>{item.filename ?? item.name}</span><small>{item.size_bytes ? bytes(item.size_bytes) : "Node pack"}{item.auth ? ` · ${item.auth} access required` : ""}</small></li>)}</ul></> : null}
    {status?.blocked?.length ? <ul className="form-error">{status.blocked.map((item, index) => <li key={index}>{item}</li>)}</ul> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    <details id="board-setup-connection" className="board-setup-connection" open={status?.state === 'failed' || status?.state === 'interrupted'}><summary>ComfyUI connection</summary>
      <p>Use the installation on the computer running Darius. Start ComfyUI, then detect it, or paste its folder path.</p>
      <label>Server address<input value={comfyUrl} disabled={busy} onChange={event => setComfyUrl(event.target.value)} placeholder="http://127.0.0.1:8188"/></label>
      <button type="button" disabled={busy} onClick={() => void connectionAction(true)}>Detect ComfyUI</button>
      <label>ComfyUI folder<input value={comfyFolder} disabled={busy} onChange={event => { setComfyFolder(event.target.value); setComfyOutput(''); }} placeholder="Folder containing main.py"/></label>
      <label>Custom output folder · optional<input value={comfyOutput} disabled={busy} onChange={event => setComfyOutput(event.target.value)} placeholder="Defaults to the ComfyUI output folder"/></label>
      <button type="button" disabled={busy || !comfyFolder.trim()} onClick={() => void connectionAction(false)}>Save connection</button>
      {connectionNotice ? <p role="status">{connectionNotice}</p> : null}
    </details>
    <label className="board-setup-restart"><input type="checkbox" checked={restart} disabled={busy} onChange={event => setRestart(event.target.checked)}/>Allow an idle ComfyUI restart to load newly installed nodes</label>
    <small>Gated models may need your own HF_TOKEN or CIVITAI_API_KEY in Darius’s local .env and acceptance of the publisher’s terms. Unknown sources and conflicting files are reported; they are not replaced.</small>
    <footer><button className="text-button" onClick={close}>{status?.state === "preparing" ? "Hide · preparation continues" : "Close"}</button>{status?.state === "ready" ? <button className="primary-button" onClick={() => { const value = active.current; active.current = null; setPending(null); value?.resolve(); }}>Continue generation</button> : <><button disabled={busy} onClick={() => void action(false)}>Check again</button>{status?.state === "needs_setup" || status?.state === "restart_required" ? <button className="primary-button" disabled={busy} onClick={() => void action(true)}><Download size={16}/>{status.stage === "compatibility" ? "Prepare ComfyUI compatibility" : "Prepare board"}</button> : null}</>}</footer>
  </div></div>, document.querySelector(".app-shell") ?? document.body);
}
