import { request } from "./api-client";
import type { CanvasDocument } from "./canvas-api";
import { commit, sameContent } from "./canvas-document";
import type { CanvasDraft, ImageRecipeConfig, MossBoard, VideoConfig } from "./moss-workspace";
import { readWorkspaceValue, rememberWorkspaceValue } from "./workspace-session";

export type PromptTarget = { boardId: string; documentId: string; name: string; archived: boolean; boardRevision: number; documentRevision: number; destination: { key: string; label: string; family: string; mode: string; maxLength: number }; text: string };
export type PromptSource = { messageId: string; draftId?: string; text: string; title: string };
export type PromptReceipt = { transferId: string; undone: boolean; target: PromptTarget; board: MossBoard; document: CanvasDocument };
export type PromptApply = { transferId: string; sourceMessageId: string; sourceDraftId?: string; sourceText: string; text: string; boardRevision: number; documentRevision: number; destination: string };
const path = (project: string, board: string) => `/projects/${encodeURIComponent(project)}/canvas-workspace/boards/${encodeURIComponent(board)}/prompt`;
export const promptApi = {
  review: (project: string, board: string) => request<PromptTarget>(path(project, board)),
  apply: (project: string, board: string, payload: PromptApply) => request<PromptReceipt>(path(project, board), { method: "POST", body: JSON.stringify(payload) }),
  undo: (project: string, board: string, transfer: string) => request<PromptReceipt>(`${path(project, board)}/${encodeURIComponent(transfer)}/undo`, { method: "POST" }),
};

export function assertCleanBoard(project: string, board: MossBoard) {
  for (const [prefix, remote] of [["h3", board.settings.video], ["image-recipe", board.settings.image]] as const) {
    const draft = readWorkspaceValue<VideoConfig | ImageRecipeConfig>(`${prefix}:${project}:${board.id}:draft`);
    if (draft && JSON.stringify(draft) !== JSON.stringify(remote)) throw new Error("This board has unsaved edits on this device. Save or reload them in the board first; your prompt is kept here.");
  }
  const draft = readWorkspaceValue<CanvasDraft>(`canvas:${project}:${board.documentId}:draft`);
  if (draft && !sameContent(draft.history.present, draft.saved)) throw new Error("This board has unsaved canvas edits. Save or reload them first; your prompt is kept here.");
}

export function acceptPromptReceipt(project: string, receipt: PromptReceipt) {
  const board = receipt.board;
  // Never replace a local draft typed while the request was in flight.
  for (const [prefix, remote] of [["h3", board.settings.video], ["image-recipe", board.settings.image]] as const) {
    const key = `${prefix}:${project}:${board.id}`;
    const base = readWorkspaceValue<number>(`${key}:base`);
    if (remote && (base === undefined || base === board.revision - 1)) {
      rememberWorkspaceValue(`${key}:draft`, remote); rememberWorkspaceValue(`${key}:base`, board.revision);
    }
  }
  const key = `canvas:${project}:${board.documentId}:draft`, draft = readWorkspaceValue<CanvasDraft>(key);
  if (draft && sameContent(draft.history.present, draft.saved)) rememberWorkspaceValue(key, { ...draft, revision: receipt.document.revision, saved: receipt.document.content, history: commit(draft.history, receipt.document.content) });
}

export function openPromptBoard(project: string, board?: string) {
  rememberWorkspaceValue(`create:${project}:section`, "canvas");
  if (board) { rememberWorkspaceValue(`moss:${project}:selected`, board); rememberWorkspaceValue(`moss:${project}:editor`, board); }
  const url = new URL(location.href); url.searchParams.set("app", "create"); url.searchParams.set("project", project);
  if (board) url.searchParams.set("board", board); else url.searchParams.delete("board");
  history.replaceState(null, "", url);
}
