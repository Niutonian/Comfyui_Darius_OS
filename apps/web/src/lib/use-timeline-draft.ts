"use client";

import { useCallback, useEffect, useState } from "react";
import { changeCut, draftPrefix, newHistory, readDrafts, redoCut, undoCut, type LocalCut, type Recovery } from "./timeline-draft";
import type { TimelineTrack, TimelineVersion } from "./types";

// Unique per document, including duplicated tabs; stable across Edit remounts.
let documentId: string | undefined;
function ownerId() { return documentId ??= crypto.randomUUID(); }

export function useTimelineDraft(projectId: string, timelineId: string, initialTracks: TimelineTrack[], latest?: TimelineVersion) {
  const [key] = useState(() => draftPrefix(projectId, timelineId) + ownerId());
  const [initial] = useState(() => {
    try {
      const records = readDrafts(localStorage, projectId, timelineId);
      return { own: records.find((record) => record.key === key), candidates: records.filter((record) => record.key !== key), error: "" };
    } catch { return { own: undefined, candidates: [], error: "Browser draft recovery is unavailable. Save a version before leaving Edit." }; }
  });
  const [history, setHistory] = useState(() => newHistory(initial.own?.cut.tracks ?? initialTracks));
  const [base, setBase] = useState(initial.own ? initial.own.cut.base : latest);
  const [baseline, setBaseline] = useState(initial.own?.cut.baseline ?? JSON.stringify(initialTracks));
  const [candidates, setCandidates] = useState(initial.candidates);
  const [recovered, setRecovered] = useState(Boolean(initial.own));
  const [recoverySource, setRecoverySource] = useState<Recovery>();
  const [storageError, setStorageError] = useState(initial.error);
  const tracks = history.present.tracks;
  const dirty = JSON.stringify(tracks) !== baseline;
  const commit = useCallback((update: TimelineTrack[] | ((current: TimelineTrack[]) => TimelineTrack[]), label = "Edit clip") => {
    setHistory((current) => changeCut(current, typeof update === "function" ? update(current.present.tracks) : update, label));
  }, []);
  function adopt(nextTracks: TimelineTrack[], version?: TimelineVersion) {
    setHistory(newHistory(nextTracks)); setBase(version); setBaseline(JSON.stringify(nextTracks)); setRecovered(false);
  }
  function markSaved(snapshot: TimelineTrack[], version: TimelineVersion) {
    setBase(version); setBaseline(JSON.stringify(snapshot)); setRecovered(false);
    // Retire a restored checkpoint only when that exact cut has been committed.
    // Never delete a newer checkpoint written by its original tab.
    if (recoverySource && JSON.stringify(recoverySource.cut.tracks) === JSON.stringify(snapshot)) {
      try {
        const stored = localStorage.getItem(recoverySource.key);
        if (stored && JSON.stringify(JSON.parse(stored)) === JSON.stringify(recoverySource.cut)) localStorage.removeItem(recoverySource.key);
      } catch { /* The saved version is already durable; an extra recovery is harmless. */ }
    }
    setRecoverySource(undefined);
  }
  function restore(record: Recovery) {
    setHistory(newHistory(record.cut.tracks)); setBase(record.cut.base); setBaseline(record.cut.baseline); setRecovered(true); setRecoverySource(record);
    setCandidates((items) => items.filter((item) => item.key !== record.key));
  }
  function discard(record: Recovery) {
    try { localStorage.removeItem(record.key); setCandidates((items) => items.filter((item) => item.key !== record.key)); }
    catch { setStorageError("Could not remove this browser recovery. Save a version to protect your cut."); }
  }
  useEffect(() => {
    let notice: ReturnType<typeof setTimeout> | undefined;
    const persist = () => {
      try {
        if (!dirty) localStorage.removeItem(key);
        else {
          const cut: LocalCut = { schema: 1, projectId, timelineId, updatedAt: new Date().toISOString(), tracks, baseline, base };
          localStorage.setItem(key, JSON.stringify(cut));
        }
      } catch { notice = setTimeout(() => setStorageError("Browser draft recovery could not be saved (storage blocked or full). Save a version before leaving Edit."), 0); }
    };
    persist();
    const beforeUnload = (event: BeforeUnloadEvent) => { persist(); if (dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", beforeUnload);
    return () => { window.removeEventListener("beforeunload", beforeUnload); if (notice) clearTimeout(notice); };
  }, [key, projectId, timelineId, tracks, baseline, base, dirty]);
  // Do not merge or replace an open cut when a different tab updates its local draft.
  useEffect(() => {
    const refresh = (event: StorageEvent) => {
      if (event.key && !event.key.startsWith(draftPrefix(projectId, timelineId))) return;
      try { setCandidates(readDrafts(localStorage, projectId, timelineId).filter((record) => record.key !== key)); } catch { /* Current cut stays usable. */ }
    };
    window.addEventListener("storage", refresh); return () => window.removeEventListener("storage", refresh);
  }, [projectId, timelineId, key]);
  return { tracks, commit, base, dirty, adopt, markSaved, candidates, restore, discard, recovered, storageError,
    canUndo: Boolean(history.past.length), canRedo: Boolean(history.future.length),
    undoLabel: history.present.label, redoLabel: history.future[0]?.label,
    undo: () => setHistory(undoCut), redo: () => setHistory(redoCut) };
}
