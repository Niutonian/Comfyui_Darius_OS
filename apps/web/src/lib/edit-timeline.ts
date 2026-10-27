import type { Asset, TimelineClip, TimelineTrack } from "./types";

export const assetName = (asset?: Asset) => asset ? String(asset.metadata.display_name || asset.metadata.original_filename || asset.metadata.filename || `${asset.kind} ${asset.id.slice(0, 8)}`) : "Missing media";
export const sequenceDuration = (tracks: TimelineTrack[]) => Math.max(0, ...tracks.flatMap((track) => track.clips.map((clip) => clip.timeline_out)));
export const pictureClips = (tracks: TimelineTrack[]) => [...(tracks.find((track) => track.kind === "video" && track.clips.length)?.clips ?? [])].sort((a, b) => a.timeline_in - b.timeline_in);
export const clipAt = (clips: TimelineClip[], time: number) => clips.find((clip) => time >= clip.timeline_in && time < clip.timeline_out);
export const sourceTime = (clip: TimelineClip, time: number) => (clip.source_in ?? 0) + Math.max(0, time - clip.timeline_in);
export function reflowClips(clips: TimelineClip[]): TimelineClip[] {
  let cursor = 0;
  return clips.map((clip) => {
    const length = Math.max(.001, (clip.source_out ?? clip.timeline_out) - (clip.source_in ?? clip.timeline_in));
    const next = { ...clip, timeline_in: cursor, timeline_out: cursor + length }; cursor += length; return next;
  });
}
export function previewIssue(tracks: TimelineTrack[], assets: Asset[]) {
  if (tracks.filter((track) => track.kind === "video" && track.clips.length).length > 1) return "This first-release player supports one picture track. Multiple picture layers are not composited yet.";
  if (tracks.some((track) => !["video", "audio"].includes(track.kind) && track.clips.length)) return "Dialogue and subtitle tracks are not rendered by this first-release player yet.";
  if (tracks.some((track) => track.clips.some((clip) => !assets.some((asset) => asset.id === clip.source_asset_id)))) return "Some source media is unavailable. Restore it or remove the affected clip before playback or render.";
  return "";
}

/** Split without reflowing: source trims and every other track keep their offsets. */
export function splitClip(tracks: TimelineTrack[], trackIndex: number, clipId: string, time: number, newId: string): TimelineTrack[] {
  const clip = tracks[trackIndex]?.clips.find((item) => item.id === clipId);
  if (!clip || !Number.isFinite(time) || time - clip.timeline_in < .001 || clip.timeline_out - time < .001) return tracks;
  const cut = (clip.source_in ?? 0) + time - clip.timeline_in;
  const envelope = (clip.fade_in || clip.fade_out) ? { audio_start: clip.audio_start ?? clip.source_in ?? 0, audio_end: clip.audio_end ?? clip.source_out ?? (clip.source_in ?? 0) + clip.timeline_out - clip.timeline_in } : {};
  return tracks.map((track, i) => i !== trackIndex ? track : { ...track, clips: track.clips.flatMap((item) => item.id !== clipId ? [item] : [
    { ...item, ...envelope, source_in: item.source_in ?? 0, source_out: cut, timeline_out: time },
    { ...item, ...envelope, id: newId, source_in: cut, source_out: item.source_out ?? (item.source_in ?? 0) + item.timeline_out - item.timeline_in, timeline_in: time },
  ]) });
}

/** Close only the removed interval on this track; retain intentional gaps elsewhere. */
export function removeClip(tracks: TimelineTrack[], trackIndex: number, clipId: string, ripple: boolean): TimelineTrack[] {
  const clip = tracks[trackIndex]?.clips.find((item) => item.id === clipId);
  if (!clip) return tracks;
  const length = clip.timeline_out - clip.timeline_in;
  return tracks.map((track, i) => i !== trackIndex ? track : { ...track, clips: track.clips.filter((item) => item.id !== clipId).map((item) =>
    ripple && item.timeline_in >= clip.timeline_out ? { ...item, timeline_in: Math.max(0, item.timeline_in - length), timeline_out: item.timeline_out - length } : item) });
}

/** Ripple a trim by its duration delta, not by packing the whole track to zero. */
export function trimClip(tracks: TimelineTrack[], trackIndex: number, clipId: string, patch: { source_in?: number; source_out?: number }, max: number, minLength = .001): TimelineTrack[] {
  const clip = tracks[trackIndex]?.clips.find((item) => item.id === clipId);
  if (!clip || !Number.isFinite(max) || Object.values(patch).some((value) => !Number.isFinite(value))) return tracks;
  const minimum = Math.min(minLength, max);
  const oldIn = clip.source_in ?? 0, oldOut = clip.source_out ?? oldIn + clip.timeline_out - clip.timeline_in;
  const sourceOut = Math.max(minimum, Math.min(max, patch.source_out ?? oldOut));
  const sourceIn = Math.max(0, Math.min(sourceOut - minimum, patch.source_in ?? oldIn));
  const end = clip.timeline_in + sourceOut - sourceIn, delta = end - clip.timeline_out;
  return tracks.map((track, i) => i !== trackIndex ? track : { ...track, clips: track.clips.map((item) => item.id === clipId
    ? { ...item, source_in: sourceIn, source_out: sourceOut, timeline_out: end }
    : item.timeline_in >= clip.timeline_out ? { ...item, timeline_in: item.timeline_in + delta, timeline_out: item.timeline_out + delta } : item) });
}
