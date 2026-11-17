"use client";
import { useEffect, useRef, useState } from "react";
import { useCanvasMiddlePan } from "@/lib/use-canvas-middle-pan";
import { useWorkspaceState } from "@/lib/workspace-session";

export type Camera = { x: number; y: number; scale: number };
export const MIN_SCALE = .15, MAX_SCALE = 2;
export const clampScale = (scale: number) => Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale));

/** Pan/zoom state for the board desktop: wheel zoom at the cursor, shift-wheel and middle-button pan. */
export function useBoardCamera(scope: string, hostKey: unknown) {
  const stage = useRef<HTMLDivElement>(null);
  const [camera, setCamera] = useWorkspaceState<Camera>(`${scope}:camera`, { x: 80, y: 60, scale: .8 });
  const [size, setSize] = useState({ width: 1000, height: 700 });
  const { panning: middlePanning, attach } = useCanvasMiddlePan(stage, camera, setCamera);
  // React delegates wheel events passively; bind locally to keep the page still.
  // Rebinds every render because the stage host can be swapped for an editor.
  useEffect(() => {
    const node = stage.current;
    if (!node) return;
    const wheel = (event: WheelEvent) => {
      if ((event.target as Element).closest("input,textarea,select,[contenteditable=true]")) return;
      event.preventDefault();
      const rect = node.getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top;
      setCamera(current => {
        if (event.shiftKey) return { ...current, x: current.x - event.deltaX, y: current.y - event.deltaY };
        if (!event.deltaY) return current;
        const scale = clampScale(current.scale * (event.deltaY > 0 ? .92 : 1.08));
        return { scale, x: x - (x - current.x) * scale / current.scale, y: y - (y - current.y) * scale / current.scale };
      });
    };
    node.addEventListener("wheel", wheel, { passive: false });
    return () => node.removeEventListener("wheel", wheel);
  });
  useEffect(() => {
    const node = stage.current; if (!node) return;
    const resize = () => setSize({ width: node.clientWidth, height: node.clientHeight }); resize();
    const observer = new ResizeObserver(resize); observer.observe(node); return () => observer.disconnect();
  }, [hostKey]);
  const zoomBy = (factor: number) => setCamera(c => ({ ...c, scale: clampScale(c.scale * factor) }));
  return { stage, attach, camera, setCamera, size, middlePanning, zoomBy };
}
