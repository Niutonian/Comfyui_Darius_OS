import type { TimelineTrack, TimelineVersion } from "./types";

export type Cut = { tracks: TimelineTrack[]; label: string };
export type EditHistory = { present: Cut; past: Cut[]; future: Cut[] };
export type LocalCut = { schema: 1; projectId: string; timelineId: string; updatedAt: string; tracks: TimelineTrack[]; baseline: string; base?: TimelineVersion };
export type Recovery = { key: string; cut: LocalCut };
export const draftPrefix = (projectId: string, timelineId: string) => `darius:edit-draft:v1:${encodeURIComponent(projectId)}:${encodeURIComponent(timelineId)}:`;
export const newHistory = (tracks: TimelineTrack[]): EditHistory => ({ present: { tracks, label: "Initial cut" }, past: [], future: [] });

export function changeCut(history: EditHistory, tracks: TimelineTrack[], label: string): EditHistory {
  if (JSON.stringify(history.present.tracks) === JSON.stringify(tracks)) return history;
  return { present: { tracks, label }, past: [...history.past, history.present].slice(-100), future: [] };
}
export function undoCut(history: EditHistory): EditHistory {
  const previous = history.past.at(-1);
  return previous ? { present: previous, past: history.past.slice(0, -1), future: [history.present, ...history.future] } : history;
}
export function redoCut(history: EditHistory): EditHistory {
  const next = history.future[0];
  return next ? { present: next, past: [...history.past, history.present].slice(-100), future: history.future.slice(1) } : history;
}

function validTracks(value: unknown): value is TimelineTrack[] {
  return Array.isArray(value) && value.every((track) => track && typeof track.kind === "string" && Array.isArray(track.clips) && track.clips.every((clip: Record<string, unknown>) =>
    clip && typeof clip.id === "string" && typeof clip.timeline_in === "number" && Number.isFinite(clip.timeline_in) && clip.timeline_in >= 0 && typeof clip.timeline_out === "number" && Number.isFinite(clip.timeline_out) && clip.timeline_out > clip.timeline_in &&
    [clip.source_in, clip.source_out].every((time) => time === undefined || (typeof time === "number" && Number.isFinite(time) && time >= 0)) &&
    [clip.fade_in, clip.fade_out, clip.audio_start, clip.audio_end].every((value) => value === undefined || (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 86400)) &&
    (clip.volume === undefined || (typeof clip.volume === "number" && Number.isFinite(clip.volume) && clip.volume >= 0 && clip.volume <= 1))));
}
export function readDrafts(storage: Storage, projectId: string, timelineId: string): Recovery[] {
  const prefix = draftPrefix(projectId, timelineId), records: Recovery[] = [];
  for (let i = 0; i < storage.length; i++) {
    const key = storage.key(i); if (!key?.startsWith(prefix)) continue;
    try {
      const cut = JSON.parse(storage.getItem(key) ?? "null") as LocalCut | null;
      if (!cut || cut.schema !== 1 || cut.projectId !== projectId || cut.timelineId !== timelineId || !Number.isFinite(Date.parse(cut.updatedAt)) || !validTracks(cut.tracks) || typeof cut.baseline !== "string" || !validTracks(JSON.parse(cut.baseline))) continue;
      if (cut.base && (cut.base.timeline_id !== timelineId || typeof cut.base.id !== "string" || !Number.isFinite(cut.base.version_number))) continue;
      if (JSON.stringify(cut.tracks) !== cut.baseline) records.push({ key, cut });
    } catch { /* A corrupt recovery never prevents opening the saved timeline. */ }
  }
  return records.sort((a, b) => Date.parse(b.cut.updatedAt) - Date.parse(a.cut.updatedAt));
}
