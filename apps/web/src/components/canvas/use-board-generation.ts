"use client";
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { canvasApi, definitiveGenerationError } from "@/lib/canvas-api";
import { canvasProfiles } from "@/lib/canvas-profile";
import { boardStatus, prepareBoard, type MossBoard, type ProjectWorkspace } from "@/lib/moss-workspace";
import { useWorkspaceState } from "@/lib/workspace-session";
import { isImageRecipeBoard } from "../image-recipe-board";
import { isVideoBoard } from "../video-board";
import { errorText } from "./use-board-layout";

export type Intent = { key: string; revision: number; seed: number | string | null; profileId?: string; boardId: string; boardRevision: number; documentId: string };

/**
 * Each board submits independently. An intent (idempotency key + snapshot) survives
 * failures so a retry never queues the same composition twice.
 */
export function useBoardGeneration({ projectId, scope, refresh, setError, onSubmit }: {
  projectId: string; scope: string; refresh: () => void; setError: (update: string | ((current: string) => string)) => void; onSubmit: (board: MossBoard) => void;
}) {
  const client = useQueryClient();
  const [intents, setIntents] = useWorkspaceState<Record<string, Intent>>(`${scope}:intents`, {});
  const [editorPreparing] = useWorkspaceState<Record<string, boolean>>(`canvas:${projectId}:preparing`, {});
  const [preparing, setPreparing] = useState<Set<string>>(new Set()), [boardErrors, setBoardErrors] = useState<Record<string, string>>({});
  const preparingIds = useRef(new Set<string>());
  const setBoardError = (boardId: string, message: string) => setBoardErrors(errors => ({ ...errors, [boardId]: message }));
  const preparingBoard = (board: MossBoard) => preparing.has(board.id) || Boolean(editorPreparing[board.documentId]);
  const statusFor = (board: MossBoard) => boardStatus(board, preparingBoard(board), boardErrors[board.id]);
  const errorFor = (board: MossBoard) => boardErrors[board.id] || board.latest?.error || "";
  const generateLabel = (board: MossBoard) => preparingBoard(board) ? "Preparing…" : board.jobs.some(job => job.status === "running" || job.status === "cancelling") ? "Rendering…" : board.jobs.length ? "Queued" : intents[board.id] ? "Retry request" : isVideoBoard(board) ? "Generate video" : isImageRecipeBoard(board) ? canvasProfiles[board.settings.adapterVersion].action : "Generate";
  const canGenerate = (board: MossBoard) => !(board.archived || preparingBoard(board) || board.jobs.length);
  const preparingCount = preparing.size + Object.values(editorPreparing).filter(Boolean).length;

  async function generate(board: MossBoard) {
    if (preparingIds.current.has(board.id)) return;
    onSubmit(board);
    setError(current => current.startsWith(`${board.name}: `) ? "" : current);
    preparingIds.current.add(board.id); setPreparing(new Set(preparingIds.current)); setBoardError(board.id, "");
    try {
      let intent = intents[board.id];
      if (!intent) { const snapshot = await prepareBoard(projectId, board); intent = { ...snapshot, key: crypto.randomUUID(), revision: snapshot.documentRevision, seed: snapshot.seed === undefined ? board.settings.seed : snapshot.seed, profileId: snapshot.profileId ?? board.settings.adapterVersion }; setIntents(i => ({ ...i, [board.id]: intent })); }
      const result = await canvasApi.generate(projectId, intent.documentId, intent.revision, intent.key, intent.seed, intent, () => setBoardError(board.id, "Checking whether your job was queued..."));
      client.setQueryData<ProjectWorkspace>(["moss-workspace", projectId], old => old ? { ...old, boards: old.boards.map(current => current.id !== board.id ? current : { ...current, latest: result, jobs: ["queued", "running", "cancelling"].includes(result.status) ? [result, ...current.jobs.filter(job => job.id !== result.id)] : current.jobs.filter(job => job.id !== result.id) }) } : old);
      setIntents(i => { const next = { ...i }; delete next[board.id]; return next; });
      setBoardError(board.id, result.launchError ?? "");
      refresh(); void client.invalidateQueries({ queryKey: ["jobs"] });
    } catch (e) {
      setBoardError(board.id, errorText(e));
      setError(`${board.name}: ${errorText(e)}`);
      if (definitiveGenerationError(e)) setIntents(i => { const next = { ...i }; delete next[board.id]; return next; });
    } finally { preparingIds.current.delete(board.id); setPreparing(new Set(preparingIds.current)); }
  }
  return { intents, setIntents, generate, preparingBoard, statusFor, errorFor, generateLabel, canGenerate, setBoardError, preparingCount };
}
