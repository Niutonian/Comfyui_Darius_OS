"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api-client";
import { mossApi, type BoardSettings, type MossBoard, type Placement, type ProjectWorkspace } from "@/lib/moss-workspace";
import { useWorkspaceState } from "@/lib/workspace-session";

export type Layout = { revision: number; saved: Placement[]; present: Placement[] };
export type UndoAction = { kind: "layout"; before: Placement[]; after: Placement[] } | { kind: "board"; boardId: string; before: BoardSettings; after: BoardSettings };
export const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
export const errorText = (error: unknown) => error instanceof Error ? error.message : "The operation failed. Your board and results are retained.";

/**
 * Board positions are a presentation draft: autosaved, revision-checked, and undoable
 * together with board settings changes.
 */
export function useBoardLayout({ projectId, scope, remote, boards, setError, refresh, isEditingPosition }: {
  projectId: string; scope: string; remote: ProjectWorkspace | undefined; boards: MossBoard[];
  setError: (message: string) => void; refresh: () => void; isEditingPosition: () => boolean;
}) {
  const client = useQueryClient();
  const [layout, setLayout] = useWorkspaceState<Layout | null>(`${scope}:layout`, null);
  const [history, setHistory] = useWorkspaceState<{ past: UndoAction[]; future: UndoAction[] }>(`${scope}:history`, { past: [], future: [] });
  const [saving, setSaving] = useState(false), [conflict, setConflict] = useState(false);
  const currentLayout = useRef(layout), savingPromise = useRef<Promise<void> | null>(null);
  useLayoutEffect(() => { currentLayout.current = layout; }, [layout]);
  const dirty = Boolean(layout && !equal(layout.present, layout.saved));

  useEffect(() => {
    if (!remote) return;
    const local = currentLayout.current;
    if (local && isEditingPosition()) {
      if (remote.revision > local.revision) { setConflict(true); setError("Workspace positions changed during this edit. Your position draft is retained; export it or reload saved positions to resolve."); }
      return;
    }
    if (!local || (!savingPromise.current && equal(local.present, local.saved))) setLayout({ revision: remote.revision, saved: remote.placements, present: remote.placements });
    else if (remote.revision > local.revision && !savingPromise.current) { setConflict(true); setError("Workspace positions changed on another device. Your position draft is retained; board generation still works."); }
  // isEditingPosition reads refs and the DOM; only remote changes should resync.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remote, setLayout, setError]);

  async function saveLayout() {
    if (savingPromise.current) return savingPromise.current;
    const local = currentLayout.current;
    if (!local || equal(local.present, local.saved) || conflict) return;
    setSaving(true);
    const work = mossApi.layout(projectId, local.revision, local.present).then(next => {
      setLayout(previous => previous ? { ...previous, revision: next.revision, saved: local.present } : previous);
      client.setQueryData(["moss-workspace", projectId], next);
    }).catch(e => { setError(errorText(e)); if (e instanceof ApiError && e.status === 409) setConflict(true); throw e; })
      .finally(() => { savingPromise.current = null; setSaving(false); });
    savingPromise.current = work; return work;
  }
  useEffect(() => { if (!dirty || saving || conflict) return; const timer = setTimeout(() => { void saveLayout().catch(() => {}); }, 650); return () => clearTimeout(timer); });

  function record(action: UndoAction) { setHistory(h => ({ past: [...h.past.slice(-49), action], future: [] })); }
  function move(placement: Placement) {
    if (!layout) return;
    const next = layout.present.map(p => p.boardId === placement.boardId ? placement : p);
    if (!equal(next, layout.present)) { record({ kind: "layout", before: layout.present, after: next }); setLayout({ ...layout, present: next }); }
  }
  /** Replace positions with a saved workspace (after an add, or a conflict reload). */
  function adopt(workspace: ProjectWorkspace) { setLayout({ revision: workspace.revision, saved: workspace.placements, present: workspace.placements }); }
  async function undoAction(forward: boolean) {
    const action = forward ? history.future[0] : history.past.at(-1); if (!action) return;
    try {
      if (action.kind === "layout") setLayout(l => l ? { ...l, present: l.present.map(p => (forward ? action.after : action.before).find(old => old.boardId === p.boardId) ?? p) } : l);
      else {
        const board = boards.find(b => b.id === action.boardId); if (!board) throw new Error("Board no longer exists");
        const saved = await mossApi.save(projectId, board, forward ? action.after : action.before);
        client.setQueryData<ProjectWorkspace>(["moss-workspace", projectId], old => old ? { ...old, boards: old.boards.map(b => b.id === saved.id ? saved : b) } : old); refresh();
      }
      setHistory(h => forward ? { past: [...h.past, action], future: h.future.slice(1) } : { past: h.past.slice(0, -1), future: [action, ...h.future] });
    } catch (e) { setError(errorText(e)); }
  }
  function clearHistory() { setHistory({ past: [], future: [] }); }
  return { layout, currentLayout, dirty, saving, conflict, setConflict, saveLayout, move, adopt, record, history, undoAction, clearHistory };
}
