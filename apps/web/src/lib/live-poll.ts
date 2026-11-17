import type { CanvasDocument } from "./canvas-api";
import type { ProjectWorkspace } from "./moss-workspace";

// Live project events (`subscribeProjectRefresh`) drive updates. Polling is only a
// fallback: brisk while work is in flight, slow otherwise.
export const BUSY_POLL_MS = 2_500;
export const IDLE_POLL_MS = 20_000;
const busy = (status: string) => status === "queued" || status === "running" || status === "cancelling";

export const workspacePoll = (query: { state: { data?: ProjectWorkspace } }) =>
  query.state.data?.boards.some(board => board.jobs.length > 0) ? BUSY_POLL_MS : IDLE_POLL_MS;
export const documentPoll = (query: { state: { data?: CanvasDocument } }) =>
  query.state.data?.generations.some(generation => busy(generation.status)) ? BUSY_POLL_MS : IDLE_POLL_MS;
