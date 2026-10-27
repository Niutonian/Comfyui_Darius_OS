import { reflowClips } from "./edit-timeline";
import type { TimelineTrack } from "./types";

export function snapTime(value: number, anchors: number[], fps: number, tolerance: number) {
  const frame = Math.max(0, Math.round(value * fps) / fps);
  const nearest = anchors.reduce((best, anchor) => Math.abs(anchor - frame) < Math.abs(best - frame) ? anchor : best, Infinity);
  return Number.isFinite(nearest) && Math.abs(nearest - frame) <= tolerance ? Math.max(0, nearest) : frame;
}

export function moveClipTo(tracks: TimelineTrack[], index: number, id: string, start: number): TimelineTrack[] {
  const clip = tracks[index]?.clips.find((item) => item.id === id);
  if (!clip || !Number.isFinite(start) || start < 0) return tracks;
  const end = start + clip.timeline_out - clip.timeline_in;
  if (tracks[index].clips.some((item) => item.id !== id && start < item.timeline_out - .000001 && end > item.timeline_in + .000001)) return tracks;
  return tracks.map((track, i) => i !== index ? track : { ...track, clips: track.clips.map((item) => item.id !== id ? item : { ...item, timeline_in: start, timeline_out: end }).sort((a, b) => a.timeline_in - b.timeline_in) });
}

export function reorderClipAt(tracks: TimelineTrack[], index: number, id: string, time: number): TimelineTrack[] {
  const clip = tracks[index]?.clips.find((item) => item.id === id);
  if (!clip || !Number.isFinite(time)) return tracks;
  const remaining = tracks[index].clips.filter((item) => item.id !== id).sort((a, b) => a.timeline_in - b.timeline_in);
  const at = remaining.findIndex((item) => time < (item.timeline_in + item.timeline_out) / 2);
  remaining.splice(at < 0 ? remaining.length : at, 0, clip);
  return tracks.map((track, i) => i !== index ? track : { ...track, clips: reflowClips(remaining) });
}

/** Edge drag is a non-ripple trim: never move neighbors, stretch media, or overlap. */
export function dragTrim(tracks: TimelineTrack[], index: number, id: string, edge: "in" | "out", target: number, sourceMax: number, fps: number): TimelineTrack[] {
  const clip = tracks[index]?.clips.find((item) => item.id === id);
  if (!clip || !Number.isFinite(target) || !Number.isFinite(sourceMax)) return tracks;
  const others = tracks[index].clips.filter((item) => item.id !== id);
  const previous = Math.max(0, ...others.filter((item) => item.timeline_out <= clip.timeline_in + .000001).map((item) => item.timeline_out));
  const next = Math.min(Infinity, ...others.filter((item) => item.timeline_in >= clip.timeline_out - .000001).map((item) => item.timeline_in));
  const minimum = Math.min(1 / fps, clip.timeline_out - clip.timeline_in);
  const sourceIn = clip.source_in ?? 0, sourceOut = clip.source_out ?? sourceIn + clip.timeline_out - clip.timeline_in;
  const bounded = edge === "in"
    ? Math.min(clip.timeline_out - minimum, Math.max(previous, clip.timeline_in - sourceIn, target))
    : Math.max(clip.timeline_in + minimum, Math.min(next, clip.timeline_out + sourceMax - sourceOut, target));
  const changed = edge === "in"
    ? { ...clip, timeline_in: bounded, source_in: Math.max(0, sourceIn + bounded - clip.timeline_in), source_out: sourceOut }
    : { ...clip, timeline_out: bounded, source_in: sourceIn, source_out: sourceOut + bounded - clip.timeline_out };
  return tracks.map((track, i) => i !== index ? track : { ...track, clips: track.clips.map((item) => item.id === id ? changed : item) });
}
