import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { connectProjectSync, subscribeProjectRefresh } from "./project-sync";

class Source extends EventTarget {
  static instances: Source[] = [];
  readyState = 1;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn(() => { this.readyState = 2; });
  constructor(public url: string) { super(); Source.instances.push(this); }
  emit(type: string, data: unknown) { this.dispatchEvent(new MessageEvent(type, { data: typeof data === "string" ? data : JSON.stringify(data) })); }
}
let dispose: (() => void) | undefined;
beforeEach(() => { vi.useFakeTimers(); Source.instances = []; vi.stubGlobal("EventSource", Source); });
afterEach(() => { dispose?.(); dispose = undefined; vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("live project synchronization", () => {
  it("coalesces bursts, filters projects, and ignores unchanged job heartbeats", () => {
    const refresh = vi.fn(), status = vi.fn(), subscriber = vi.fn();
    const unsubscribe = subscribeProjectRefresh("p", subscriber);
    dispose = connectProjectSync("p", "/events", refresh, status);
    const source = Source.instances[0];
    source.onopen?.(); source.emit("ready", {});
    vi.advanceTimersByTime(200);
    expect(refresh).toHaveBeenLastCalledWith({ projectId: "p", full: true, types: [] });
    refresh.mockClear(); subscriber.mockClear();
    source.emit("project_event", { project_id: "other", event_type: "conversation.created" });
    source.emit("jobs", []); source.emit("jobs", []);
    source.emit("project_event", { project_id: "p", event_type: "conversation.message_created" });
    source.emit("project_event", { project_id: "p", event_type: "conversation.assistant_replied" });
    vi.advanceTimersByTime(200);
    expect(refresh).toHaveBeenCalledOnce();
    expect(subscriber).toHaveBeenCalledWith({ projectId: "p", full: false, types: ["job.snapshot", "conversation.message_created", "conversation.assistant_replied"] });
    source.emit("jobs", []); vi.advanceTimersByTime(200);
    expect(refresh).toHaveBeenCalledOnce(); unsubscribe();
  });

  it("catches up after reconnect, focus, and periodic reconciliation, and cleans up", () => {
    const refresh = vi.fn(), status = vi.fn();
    dispose = connectProjectSync("p", "/events", refresh, status);
    const source = Source.instances[0];
    source.onerror?.(); expect(status).toHaveBeenLastCalledWith("reconnecting");
    source.onopen?.(); vi.advanceTimersByTime(200);
    expect(status).toHaveBeenLastCalledWith("live");
    expect(refresh).toHaveBeenCalledOnce();
    window.dispatchEvent(new Event("focus")); vi.advanceTimersByTime(200);
    expect(refresh).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(15_000); expect(refresh).toHaveBeenCalledTimes(3);
    dispose(); dispose = undefined;
    window.dispatchEvent(new Event("focus")); vi.advanceTimersByTime(30_000);
    expect(source.close).toHaveBeenCalledOnce(); expect(refresh).toHaveBeenCalledTimes(3);
  });

  it("keeps a bounded polling fallback if EventSource is unavailable", () => {
    vi.stubGlobal("EventSource", undefined);
    const refresh = vi.fn(), status = vi.fn();
    dispose = connectProjectSync("p", "/events", refresh, status);
    expect(status).toHaveBeenLastCalledWith("polling");
    vi.advanceTimersByTime(15_200); expect(refresh).toHaveBeenCalledOnce();
  });
});
