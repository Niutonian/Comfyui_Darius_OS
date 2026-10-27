/** One server event connection per open project; subscribers only reread persisted data. */
export type ProjectRefresh = { projectId: string; types: string[]; full: boolean };
export type SyncStatus = "connecting" | "live" | "reconnecting" | "offline" | "polling";
const listeners = new Set<(change: ProjectRefresh) => void>();

export function publishProjectRefresh(change: ProjectRefresh) {
  for (const listener of listeners) listener(change);
}

export function subscribeProjectRefresh(projectId: string, listener: (change: ProjectRefresh) => void) {
  const scoped = (change: ProjectRefresh) => { if (change.projectId === projectId) listener(change); };
  listeners.add(scoped);
  return () => { listeners.delete(scoped); };
}

export function connectProjectSync(projectId: string, url: string, refresh: (change: ProjectRefresh) => void, status: (state: SyncStatus) => void) {
  let source: EventSource | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let full = false;
  let jobs = "";
  const types = new Set<string>();
  const schedule = (type?: string) => {
    if (type) types.add(type); else full = true;
    if (timer) return;
    timer = setTimeout(() => {
      timer = undefined;
      const change = { projectId, types: [...types], full };
      types.clear(); full = false;
      refresh(change); publishProjectRefresh(change);
    }, 200);
  };
  const recover = () => {
    if (document.visibilityState === "hidden") return;
    if (!navigator.onLine) { status("offline"); return; }
    schedule();
    if (source?.readyState === 2) { source.close(); open(); }
  };
  const open = () => {
    if (typeof EventSource === "undefined") { status("polling"); return; }
    source = new EventSource(url);
    source.onopen = () => { status("live"); schedule(); };
    // Ready follows the server's initial cursor: reread after that barrier to avoid a startup race.
    source.addEventListener("ready", () => schedule());
    source.addEventListener("project_event", (raw) => {
      try {
        const event = JSON.parse((raw as MessageEvent<string>).data);
        if (event.project_id === projectId && typeof event.event_type === "string") schedule(event.event_type);
      } catch { schedule(); }
    });
    source.addEventListener("jobs", (raw) => {
      const snapshot = (raw as MessageEvent<string>).data;
      if (snapshot !== jobs) { jobs = snapshot; schedule("job.snapshot"); }
    });
    source.onerror = () => status(navigator.onLine ? "reconnecting" : "offline");
  };
  status(navigator.onLine ? "connecting" : "offline");
  open();
  // Bounded reconciliation also covers missed events, global defaults, and a sleeping phone.
  const fallback = setInterval(recover, 15_000);
  const offline = () => status("offline");
  window.addEventListener("online", recover);
  window.addEventListener("offline", offline);
  window.addEventListener("focus", recover);
  document.addEventListener("visibilitychange", recover);
  return () => {
    source?.close(); if (timer) clearTimeout(timer); clearInterval(fallback);
    window.removeEventListener("online", recover); window.removeEventListener("offline", offline);
    window.removeEventListener("focus", recover); document.removeEventListener("visibilitychange", recover);
  };
}
