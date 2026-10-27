"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { dragTrim, moveClipTo, reorderClipAt, snapTime } from "@/lib/timeline-motion";
import { sequenceDuration } from "@/lib/edit-timeline";
import type { Asset, TimelineClip, TimelineTrack } from "@/lib/types";
import { EditThumbnail } from "./edit-thumbnail";
import { ClipWaveform } from "./clip-waveform";
import { editClock } from "./sequence-player";

type Gesture = { origin: TimelineTrack[]; fingerprint: string; index: number; id: string; edge: "move" | "in" | "out"; startX: number; scrollLeft: number; secondsPerPixel: number; sourceMax: number; pointerId: number };
type Props = { tracks: TimelineTrack[]; assets: Asset[]; time: number; fps: number; zoom: number; selectedId: string | null; selectedTrack: number; snapping: boolean; onSnapping: (value: boolean) => void; clipName: (clip: TimelineClip) => string; onSelect: (clip: TimelineClip, index: number) => void; onSeek: (time: number) => void; onCommit: (tracks: TimelineTrack[], label: string) => void; onInteraction: () => void };

export function TimelineStrip({ tracks, assets, time, fps, zoom, selectedId, selectedTrack, snapping, onSnapping, clipName, onSelect, onSeek, onCommit, onInteraction }: Props) {
  const [mode, setMode] = useState<"move" | "reorder">("move");
  const [preview, setPreview] = useState<TimelineTrack[] | null>(null);
  const [dragOrigin, setDragOrigin] = useState<TimelineTrack[] | null>(null);
  const [notice, setNotice] = useState("");
  const [invalid, setInvalid] = useState(false);
  const gesture = useRef<Gesture | null>(null), suppressClick = useRef(false), current = useRef(tracks);
  const root = useRef<HTMLDivElement>(null);
  const duration = sequenceDuration(tracks), span = Math.max(10, duration + Math.max(2, duration * .1));
  // Reposition visually during a drag, but keep DOM sibling order stable. Moving a
  // captured element in the DOM can release pointer capture before pointer-up.
  const displayed = preview && dragOrigin ? preview.map((track, index) => {
    const order = new Map(dragOrigin[index].clips.map((clip, i) => [clip.id, i]));
    return { ...track, clips: [...track.clips].sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0)) };
  }) : tracks;
  useEffect(() => { current.current = tracks; }, [tracks]);
  useEffect(() => {
    const cancel = (event: KeyboardEvent) => {
      if (event.key === "Escape" && gesture.current) { gesture.current = null; setPreview(null); setInvalid(false); setNotice("Drag cancelled. Your cut was not changed."); }
    };
    window.addEventListener("keydown", cancel); return () => window.removeEventListener("keydown", cancel);
  }, []);

  function begin(event: PointerEvent<HTMLElement>, clip: TimelineClip, index: number, edge: Gesture["edge"]) {
    if (event.button !== 0 || gesture.current) return;
    event.preventDefault(); event.stopPropagation();
    const lane = event.currentTarget.closest(".desk-track-lane")?.getBoundingClientRect(); if (!lane?.width) return;
    const asset = assets.find((item) => item.id === clip.source_asset_id);
    gesture.current = { origin: tracks, fingerprint: JSON.stringify(tracks), index, id: clip.id, edge, startX: event.clientX, scrollLeft: root.current?.closest(".desk-timeline-scroll")?.scrollLeft ?? 0, secondsPerPixel: span / lane.width, sourceMax: asset?.duration ?? 86400, pointerId: event.pointerId };
    event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
    suppressClick.current = false; setDragOrigin(tracks); setNotice(""); setInvalid(false); onInteraction(); onSelect(clip, index);
  }
  function calculate(event: PointerEvent<HTMLElement>) {
    const drag = gesture.current; if (!drag || drag.pointerId !== event.pointerId) return null;
    const clip = drag.origin[drag.index].clips.find((item) => item.id === drag.id)!;
    const scrolled = (root.current?.closest(".desk-timeline-scroll")?.scrollLeft ?? 0) - drag.scrollLeft;
    const delta = (event.clientX - drag.startX + scrolled) * drag.secondsPerPixel, length = clip.timeline_out - clip.timeline_in;
    const anchors = [0, time, ...drag.origin.flatMap((track, index) => track.clips.filter((item) => index !== drag.index || item.id !== drag.id).flatMap((item) => [item.timeline_in, item.timeline_out]))];
    let target = (drag.edge === "out" ? clip.timeline_out : clip.timeline_in) + delta;
    target = snapTime(target, snapping && !event.shiftKey ? drag.edge === "move" ? [...anchors, ...anchors.map((anchor) => anchor - length)] : anchors : [], fps, 8 * drag.secondsPerPixel);
    const next = drag.edge !== "move" ? dragTrim(drag.origin, drag.index, drag.id, drag.edge, target, drag.sourceMax, fps)
      : mode === "reorder" ? reorderClipAt(drag.origin, drag.index, drag.id, target + length / 2)
      : moveClipTo(drag.origin, drag.index, drag.id, target);
    return { next, invalid: next === drag.origin && Math.abs(delta) > 1 / fps, moved: Math.abs(event.clientX - drag.startX) >= 3 };
  }
  function move(event: PointerEvent<HTMLElement>) {
    const result = calculate(event); if (!result) return;
    if (result.moved) suppressClick.current = true;
    setPreview(result.next); setInvalid(result.invalid);
    // Pointer capture keeps the drag alive while the horizontally scrolling lane moves.
    const scroll = root.current?.closest(".desk-timeline-scroll");
    if (scroll) { const rect = scroll.getBoundingClientRect(); if (event.clientX > rect.right - 28) scroll.scrollLeft += 12; else if (event.clientX < rect.left + 28) scroll.scrollLeft -= 12; }
  }
  function finish(event: PointerEvent<HTMLElement>, cancel = false) {
    const drag = gesture.current, result = calculate(event); if (!drag) return;
    gesture.current = null; setPreview(null); setInvalid(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (cancel) { setNotice("Drag cancelled. Your cut was not changed."); return; }
    if (JSON.stringify(current.current) !== drag.fingerprint) { setNotice("The cut changed during the drag. Please try again; nothing was overwritten."); return; }
    if (result?.moved && !result.invalid) onCommit(result.next, drag.edge === "move" ? mode === "reorder" ? "Drag reorder" : "Move clip" : "Drag trim");
    else if (result?.invalid) setNotice("That move overlaps another clip. Choose a gap, or use Reorder mode to insert it into the assembly.");
  }
  return <>
    <div className="desk-drag-tools"><label>Drag mode<select aria-label="Timeline drag mode" value={mode} onChange={(event) => setMode(event.target.value as typeof mode)}><option value="move">Move · preserve gaps</option><option value="reorder">Reorder · close gaps</option></select></label><button type="button" className="secondary-button" aria-pressed={snapping} onClick={() => onSnapping(!snapping)}>Snap {snapping ? "on" : "off"} · N</button><small>Drag the body to move; drag either edge to trim. Shift temporarily disables snapping. Esc cancels.</small></div>
    {notice ? <p className="desk-drag-notice" role="status">{notice}</p> : null}
    <div className="desk-timeline-scroll"><div ref={root} className={`desk-timeline-content ${invalid ? "is-invalid-drag" : ""}`} style={{ minWidth: Math.max(520, span * zoom) + 58 }}>
      <div className="desk-ruler"><span />{[0, .2, .4, .6, .8, 1].map((fraction) => <button type="button" key={fraction} aria-label={`Seek to ${editClock(span * fraction)}`} style={{ left: `calc(58px + (100% - 58px) * ${fraction})` }} onClick={() => onSeek(Math.min(duration, span * fraction))}>{editClock(span * fraction)}</button>)}</div>
      {displayed.map((track, index) => <div className="desk-track" key={index}><span className="desk-track-label">{track.kind === "video" ? "V" : track.kind === "audio" ? "A" : "T"}{index + 1}</span><div className="desk-track-lane" aria-label={`${track.kind} track ${index + 1}`}>
        {track.clips.map((clip) => <div key={clip.id} data-clip-id={clip.id} data-start={clip.timeline_in} data-end={clip.timeline_out} className={`desk-film-item ${selectedId === clip.id && selectedTrack === index ? "is-selected" : ""}`} style={{ left: `${clip.timeline_in / span * 100}%`, width: `${(clip.timeline_out - clip.timeline_in) / span * 100}%` }}>
          <button type="button" aria-label={`Select ${clipName(clip)}`} aria-pressed={selectedId === clip.id && selectedTrack === index} className={`desk-film-clip ${track.kind === "audio" ? "is-audio" : ""} ${clip.muted ? "is-muted" : ""}`} onPointerDown={(event) => begin(event, clip, index, "move")} onPointerMove={move} onPointerUp={(event) => finish(event)} onPointerCancel={(event) => finish(event, true)} onLostPointerCapture={(event) => { if (gesture.current) finish(event, true); }} onClick={() => { if (!suppressClick.current) onSelect(clip, index); suppressClick.current = false; }}>
            <EditThumbnail asset={assets.find((asset) => asset.id === clip.source_asset_id)} assets={assets} /><ClipWaveform asset={assets.find((asset) => asset.id === clip.source_asset_id)} clip={clip} /><span>{clipName(clip)}</span><small>{editClock(clip.timeline_out - clip.timeline_in)}{clip.muted ? " · muted" : ""}</small>
          </button>
          {(["in", "out"] as const).map((edge) => <button key={edge} type="button" className={`desk-trim-handle trim-${edge}`} aria-label={`Drag trim ${edge}: ${clipName(clip)}`} title={`Drag to trim ${edge}; use [ / ] for start, Shift+[ / ] for end`} onPointerDown={(event) => begin(event, clip, index, edge)} onPointerMove={move} onPointerUp={(event) => finish(event)} onPointerCancel={(event) => finish(event, true)} onLostPointerCapture={(event) => { if (gesture.current) finish(event, true); }} />)}
        </div>)}
      </div></div>)}
      <div className="desk-playhead" aria-hidden style={{ left: `calc(58px + (100% - 58px) * ${Math.min(time, span) / span})` }} />
    </div></div>
  </>;
}
