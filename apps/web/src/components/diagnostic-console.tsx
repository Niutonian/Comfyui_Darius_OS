"use client";

import { Copy, Download, RefreshCw, Terminal, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE, ApiError } from "@/lib/api-client";

export type Diagnostics = {
  generated_at: string; project_id: string | null; provider: string; model: string;
  failures: { id: string; source: string; time: string; detail: string }[];
  checks: { name: string; state: string; detail: string }[];
  logs: Record<string, string>; activities: { message_id: string; activity: unknown[] }[];
};

export function diagnosticReport(data: Diagnostics) {
  return [`Darius local diagnostic report · ${data.generated_at}`, `Project: ${data.project_id ?? "none"}`,
    `Model: ${data.provider} / ${data.model}`, "Review before sharing: ComfyUI terminal output may contain private content.",
    "\nSERVICE CHECKS", ...data.checks.map((check) => `${check.name}: ${check.state} · ${check.detail}`),
    "\nPROJECT FAILURES", ...data.failures.map((failure) => `${failure.time} [${failure.source}] ${failure.id}\n${failure.detail}`),
    "\nPROJECT TOOL ACTIVITY", JSON.stringify(data.activities, null, 2),
    ...Object.entries(data.logs).map(([name, log]) => `\n${name.toUpperCase()} LOG\n${log || "No activity recorded yet."}`)].join("\n");
}

async function readDiagnostics(projectId: string | null, key: string, logs: boolean, signal: AbortSignal): Promise<Diagnostics> {
  const params = new URLSearchParams({ logs: String(logs) });
  if (projectId) params.set("project_id", projectId);
  const response = await fetch(`${API_BASE}/diagnostics?${params}`, { signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]), cache: "no-store",
    headers: { "X-Darius-Diagnostics-Key": key } });
  if (!response.ok) throw new ApiError(response.status === 401 ? "Incorrect access code. Unlock the console again." : "Local diagnostics unavailable.", response.status);
  return response.json();
}

export function DiagnosticConsole({ projectId }: { projectId: string | null }) {
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [authVersion, setAuthVersion] = useState(0);
  const [entered, setEntered] = useState("");
  const [tab, setTab] = useState("backend");
  const [paused, setPaused] = useState(false);
  const [follow, setFollow] = useState(true);
  const [notice, setNotice] = useState("");
  const [dismissed, setDismissed] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const output = useRef<HTMLPreElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const queryClient = useQueryClient();
  useEffect(() => {
    // Load browser-only credentials after hydration; never send them in a URL.
    const saved = sessionStorage.getItem("darius-diagnostics-key");
    if (saved) { const timer = setTimeout(() => setKey(saved), 0); return () => clearTimeout(timer); }
  }, []);
  const query = useQuery({ queryKey: ["diagnostics", projectId, open, authVersion],
    queryFn: ({ signal }) => readDiagnostics(projectId, key, open, signal), enabled: Boolean(key), retry: false,
    refetchInterval: paused && open ? false : open ? 5000 : 15000,
    refetchIntervalInBackground: false });
  useEffect(() => {
    if (open) { previousFocus.current = document.activeElement as HTMLElement; dialog.current?.showModal(); }
    else { dialog.current?.close(); previousFocus.current?.focus(); }
  }, [open]);
  const data = query.data;
  useEffect(() => { if (follow && output.current) output.current.scrollTop = output.current.scrollHeight; }, [data, tab, follow]);
  const newest = data?.failures[0];
  const offline = data?.checks.find((check) => check.state === "offline");
  const problemId = offline ? `offline:${offline.name}` : newest?.id;
  function unlock() {
    void queryClient.cancelQueries({ queryKey: ["diagnostics"] });
    queryClient.removeQueries({ queryKey: ["diagnostics"] });
    sessionStorage.setItem("darius-diagnostics-key", entered.trim());
    setKey(entered.trim()); setEntered(""); setAuthVersion(value => value + 1);
  }
  function lock() {
    void queryClient.cancelQueries({ queryKey: ["diagnostics"] });
    sessionStorage.removeItem("darius-diagnostics-key");
    queryClient.removeQueries({ queryKey: ["diagnostics"] }); setKey(""); setAuthVersion(value => value + 1);
  }
  async function copy() {
    if (!data) return;
    try { await navigator.clipboard.writeText(diagnosticReport(data)); setNotice("Report copied. Review it before sharing."); }
    catch { setNotice("Clipboard unavailable. Use Download report instead."); }
  }
  function download() {
    if (!data) return;
    const url = URL.createObjectURL(new Blob([diagnosticReport(data)], { type: "text/plain" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "darius-diagnostics.txt"; anchor.click(); URL.revokeObjectURL(url);
  }
  const authenticationFailed = query.error instanceof ApiError && query.error.status === 401;
  return <>
    <button aria-label="Open diagnostic console" aria-haspopup="dialog" className={`settings-launch console-launch ${open ? "active" : ""} ${key && problemId ? "has-failure" : ""}`} title={problemId ? "Console · failure recorded" : "Local diagnostic console"} type="button" onClick={() => setOpen(true)}><Terminal size={17} />{key && problemId ? <i aria-hidden="true" /> : null}</button>
    {key && problemId && problemId !== dismissed && !open ? <div className="diagnostic-alert" role="status"><span>{offline ? `${offline.name} is offline` : "Local task needs attention"}</span><button onClick={() => setOpen(true)} type="button">View console</button><button aria-label="Dismiss failure notification" type="button" onClick={() => setDismissed(problemId)}><X size={14} /></button></div> : null}
    <dialog ref={dialog} className="diagnostic-console" aria-labelledby="console-title" onCancel={() => setOpen(false)} onClose={() => setOpen(false)}>
      <header><div><Terminal size={19} /><h2 id="console-title">Local console</h2></div><button aria-label="Close diagnostic console" className="icon-button" onClick={() => setOpen(false)} type="button"><X size={18} /></button></header>
      {!key || authenticationFailed ? <form className="console-unlock" onSubmit={(event) => { event.preventDefault(); unlock(); }}>
        <p>Use <strong>Console code</strong> in the Darius Windows manager on the computer running the API. It opens the correct <code>data/diagnostics/access-code.txt</code> for that installation. A code from another machine will not unlock this server.</p>
        {authenticationFailed ? <p role="alert">{query.error?.message}</p> : null}
        <label>Local access code<input autoComplete="off" type="password" value={entered} onChange={(event) => setEntered(event.target.value)} required /></label><button type="submit">Unlock console</button>
      </form> : <>
        <div className="console-toolbar"><button type="button" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw size={14} /> Check now</button><label><input type="checkbox" checked={!paused} onChange={() => setPaused(!paused)} /> Live (5s)</label><label><input type="checkbox" checked={follow} onChange={() => setFollow(!follow)} /> Follow logs</label><button type="button" onClick={() => void copy()} disabled={!data}><Copy size={14} /> Copy report</button><button type="button" onClick={download} disabled={!data}><Download size={14} /> Download</button><button type="button" onClick={lock}>Lock</button></div>
        <p className="console-warning">Project failures are scoped to this project. Service logs are machine-wide and may contain private content. Keys are redacted; review reports before sharing.</p>
        {query.error ? <p role="alert">{query.error.message} The last snapshot remains below.</p> : null}
        {query.isLoading ? <p role="status">Checking local services…</p> : null}
        <div className="console-checks">{data?.checks.map((check) => <div key={check.name} data-state={check.state}><strong>{check.name} · {check.state}</strong><small>{check.detail}</small></div>)}</div>
        <div className="console-tabs" role="tablist" aria-label="Console log source">{["backend", "comfyui", "jobs", "failures"].map((name) => <button key={name} role="tab" aria-selected={tab === name} aria-controls="console-output" type="button" onClick={() => setTab(name)}>{name === "comfyui" ? "ComfyUI" : name === "jobs" ? "Worker" : name === "failures" ? `Failures (${data?.failures.length ?? 0})` : "Backend"}</button>)}</div>
        <pre ref={output} id="console-output" role="tabpanel" aria-label={`${tab} log`} tabIndex={0}>{tab === "failures" ? data?.failures.map((failure) => `${failure.time} [${failure.source}] ${failure.id}\n${failure.detail}`).join("\n\n") || "No failed tasks in the recent project history." : data?.logs[tab] || "No log activity recorded yet."}</pre>
        <footer><span>{query.isFetching ? "Refreshing…" : data ? `Updated ${new Date(data.generated_at).toLocaleTimeString()}` : "Waiting for diagnostics"}</span><span>Logs scroll independently · reports include all sources</span></footer>
      </>}
      <p className="console-notice" role="status">{notice}</p>
    </dialog>
  </>;
}
