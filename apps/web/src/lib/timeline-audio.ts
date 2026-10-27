import { sourceTime } from "./edit-timeline";
import type { Asset, TimelineClip } from "./types";

export function knownAudio(asset?: Asset): boolean | undefined {
  if (!asset || !["audio", "video"].includes(asset.kind)) return false;
  if (asset.kind === "audio") return true;
  const probe = asset.metadata.ffprobe as { streams?: Array<{ codec_type?: string }> } | undefined;
  return Array.isArray(probe?.streams) ? probe.streams.some((stream) => stream.codec_type === "audio") : undefined;
}
export function audioGain(clip: TimelineClip, time: number) {
  if (clip.muted) return 0;
  const start = clip.audio_start ?? clip.source_in ?? 0;
  const end = clip.audio_end ?? clip.source_out ?? (clip.source_in ?? 0) + clip.timeline_out - clip.timeline_in;
  const position = sourceTime(clip, time);
  const fadeIn = clip.fade_in ? Math.min(1, Math.max(0, (position - start) / clip.fade_in)) : 1;
  const fadeOut = clip.fade_out ? Math.min(1, Math.max(0, (end - position) / clip.fade_out)) : 1;
  return Math.min(1, Math.max(0, clip.volume ?? 1)) * fadeIn * fadeOut;
}
