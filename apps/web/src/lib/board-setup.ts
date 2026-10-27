import { ApiError, request } from "./api-client";

export type BoardSetup = {
  profile: string;
  state: "unchecked" | "checking" | "needs_setup" | "preparing" | "blocked" | "ready" | "failed" | "interrupted" | "restart_required";
  message?: string;
  stage?: string;
  planDigest?: string;
  blocked?: string[];
  actions?: { kind: string; filename?: string; name?: string; size_bytes?: number; auth?: string; url?: string }[];
  progress?: { phase?: string; message?: string; bytes_done?: number; bytes_total?: number; speed?: number; eta?: number };
};
export type BoardSetupRequest = { profile: string; resolve: () => void; reject: (reason: Error) => void };
export type ComfyConnection = { root: string; baseUrl: string; configured: boolean; outputDir?: string; saved?: boolean; cliReady?: boolean };
const listeners = new Set<(value: BoardSetupRequest) => void>();
export function subscribeBoardSetup(listener: (value: BoardSetupRequest) => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function requestBoardSetup(profile: string): Promise<void> {
  if (!listeners.size) return Promise.reject(new ApiError("This board needs preparation. Open Create → Canvas and retry Generate.", 422));
  return new Promise((resolve, reject) => { for (const listener of listeners) listener({ profile, resolve, reject }); });
}
const path = (profile: string) => `/canvas/setup/${encodeURIComponent(profile)}`;
export const boardSetupApi = {
  connection: () => request<ComfyConnection>('/canvas/connection'),
  detect: (baseUrl: string) => request<ComfyConnection>('/canvas/connection/detect', { method: 'POST', body: JSON.stringify({ baseUrl }) }),
  connect: (root: string, baseUrl: string, outputDir = '') => request<ComfyConnection>('/canvas/connection', { method: 'POST', body: JSON.stringify({ root, baseUrl, outputDir }) }),
  status: (profile: string) => request<BoardSetup>(path(profile)),
  check: (profile: string) => request<BoardSetup>(`${path(profile)}/check`, { method: "POST" }),
  prepare: (profile: string, planDigest: string, restart: boolean) => request<BoardSetup>(`${path(profile)}/prepare`, { method: "POST", body: JSON.stringify({ planDigest, restart }) }),
};
