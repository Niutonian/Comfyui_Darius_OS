import { expect, it } from "vitest";
import { workspaceStatus } from "./workspace-status";
import type { Health, Job } from "./types";
const health: Health = { status: "ok", components: { database: { ready: true }, comfyui: { ready: true }, optional: { ready: false, configured: false } } };
const running = { status: "running" } as Job;
it("prioritizes sync trouble without discarding concurrent running jobs", () => {
  const jobs = [running];
  expect(workspaceStatus({ health, sync: "offline", mood: "thinking", jobs })).toMatchObject({ label: "Sync offline", tone: "error" });
  expect(jobs).toEqual([running]);
  expect(workspaceStatus({ health, sync: "live", mood: "thinking", jobs })).toMatchObject({ label: "1 active job", tone: "generating" });
});
it("uses precise local readiness, not readiness of every optional service", () => {
  expect(workspaceStatus({ health, sync: "live", mood: "idle", jobs: [] }).label).toBe("Local ready");
  expect(workspaceStatus({ health: { ...health, components: {} }, mood: "idle", jobs: [] }).label).toBe("Local unavailable");
});
it("keeps actionable issues ahead of activity", () => {
  expect(workspaceStatus({ health, mood: "speaking", jobs: [running, { status: "failed" } as Job] }).label).toBe("1 job needs attention");
  expect(workspaceStatus({ health, error: true, mood: "idle", jobs: [running] }).label).toBe("Server unavailable");
});
