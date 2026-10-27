"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";
import { audioGain, knownAudio } from "@/lib/timeline-audio";
import type { Asset, TimelineClip } from "@/lib/types";

export function ClipWaveform({ asset, clip }: { asset?: Asset; clip: TimelineClip }) {
  const target = useRef<HTMLSpanElement>(null), [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!target.current || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.disconnect(); } });
    observer.observe(target.current); return () => observer.disconnect();
  }, []);
  const audio = useQuery({ queryKey: ["edit-audio-preview", asset?.project_id, asset?.id], queryFn: () => api.audioPreview(asset!.id, asset!.project_id), enabled: visible && Boolean(asset) && knownAudio(asset) !== false, staleTime: Infinity, gcTime: 300_000, retry: 1, retryDelay: 2500 });
  const data = audio.data, length = clip.timeline_out - clip.timeline_in;
  const bars = data?.has_audio && data.peaks.length && data.duration > 0 ? Array.from({ length: 64 }, (_, i) => {
    const relative = (i + .5) / 64 * length, source = (clip.source_in ?? 0) + relative;
    const index = Math.floor(source / data.duration * data.peaks.length);
    // Never fabricate peaks beyond the bounded decoded region.
    const peak = source < data.duration && index >= 0 ? data.peaks[Math.min(index, data.peaks.length - 1)] ?? 0 : 0;
    return Math.max(0, Math.min(1, peak * audioGain(clip, clip.timeline_in + relative)));
  }) : [];
  const description = audio.isError ? "Waveform unavailable; playback is still available" : data?.has_audio === false ? "No embedded audio" : data?.partial ? "Waveform preview covers the first 30 minutes of source audio" : "Audio waveform";
  return <span ref={target} className="desk-waveform" title={description} aria-label={description}>{bars.length ? <svg viewBox="0 0 256 32" preserveAspectRatio="none" aria-hidden="true">{bars.map((peak, i) => <rect key={i} x={i * 4} y={16 - peak * 15} width={2} height={Math.max(.5, peak * 30)} />)}</svg> : audio.isError ? <span>Waveform unavailable</span> : null}</span>;
}
