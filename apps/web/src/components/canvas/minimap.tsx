"use client";
import { useRef } from "react";
import type { Placement } from "@/lib/moss-workspace";
import type { Camera } from "./use-board-camera";

const W = 176, H = 112, PAD = 8;

/** Bounds of every board plus what is on screen, so the view box is always visible. */
export function minimapFrame(placements: Placement[], camera: Camera, size: { width: number; height: number }) {
  const view = { x: -camera.x / camera.scale, y: -camera.y / camera.scale, width: size.width / camera.scale, height: size.height / camera.scale };
  const left = Math.min(view.x, ...placements.map(p => p.x)), top = Math.min(view.y, ...placements.map(p => p.y));
  const right = Math.max(view.x + view.width, ...placements.map(p => p.x + p.displayWidth)), bottom = Math.max(view.y + view.height, ...placements.map(p => p.y + p.displayHeight));
  const scale = Math.min((W - PAD * 2) / Math.max(1, right - left), (H - PAD * 2) / Math.max(1, bottom - top));
  return { view, left, top, scale, offsetX: (W - (right - left) * scale) / 2, offsetY: (H - (bottom - top) * scale) / 2 };
}

/**
 * Overview of the whole canvas. Click or drag to move the view; the selected board
 * is highlighted, busy boards pulse.
 */
export function Minimap({ placements, camera, size, selectedId, busyIds, onCamera }: {
  placements: Placement[]; camera: Camera; size: { width: number; height: number }; selectedId: string | null; busyIds: Set<string>; onCamera: (camera: Camera) => void;
}) {
  const svg = useRef<SVGSVGElement>(null), dragging = useRef(false);
  const frame = minimapFrame(placements, camera, size);
  const toMap = (x: number, y: number) => ({ x: (x - frame.left) * frame.scale + frame.offsetX, y: (y - frame.top) * frame.scale + frame.offsetY });
  function centre(clientX: number, clientY: number) {
    const rect = svg.current!.getBoundingClientRect();
    const worldX = (clientX - rect.left - frame.offsetX) / frame.scale + frame.left, worldY = (clientY - rect.top - frame.offsetY) / frame.scale + frame.top;
    onCamera({ ...camera, x: size.width / 2 - worldX * camera.scale, y: size.height / 2 - worldY * camera.scale });
  }
  const view = toMap(frame.view.x, frame.view.y);
  return <svg ref={svg} className="dk-minimap" width={W} height={H} role="img" aria-label="Canvas overview. Click to move the view."
    onPointerDown={event => { dragging.current = true; event.currentTarget.setPointerCapture(event.pointerId); centre(event.clientX, event.clientY); }}
    onPointerMove={event => { if (dragging.current) centre(event.clientX, event.clientY); }}
    onPointerUp={() => { dragging.current = false; }} onPointerCancel={() => { dragging.current = false; }}>
    {placements.map(p => { const at = toMap(p.x, p.y); return <rect key={p.boardId} className={`${p.boardId === selectedId ? "is-selected" : ""} ${busyIds.has(p.boardId) ? "is-busy" : ""}`} x={at.x} y={at.y} width={Math.max(2, p.displayWidth * frame.scale)} height={Math.max(2, p.displayHeight * frame.scale)} rx={2} />; })}
    <rect className="dk-minimap-view" x={view.x} y={view.y} width={frame.view.width * frame.scale} height={frame.view.height * frame.scale} rx={3} />
  </svg>;
}
