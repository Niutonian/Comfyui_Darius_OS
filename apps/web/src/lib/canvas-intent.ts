// Only transport identity, never prompts/images/credentials, survives reload.
export type CanvasIntent = { revision: number; key: string; seed: number | string | null; profileId?: string; promotedFromGenerationId?: string; boardId?: string; boardRevision?: number; documentId: string };
const key = (project: string, document: string) => `darius-canvas-intent:${project}:${document}`;
export function loadCanvasIntent(project: string, document: string): CanvasIntent | undefined {
  try { return JSON.parse(sessionStorage.getItem(key(project, document)) || "null") ?? undefined; } catch { return undefined; }
}
export function saveCanvasIntent(project: string, document: string, intent?: CanvasIntent) {
  try { if (intent) sessionStorage.setItem(key(project, document), JSON.stringify(intent)); else sessionStorage.removeItem(key(project, document)); } catch { /* Memory-only retry still works if browser storage is disabled. */ }
}
