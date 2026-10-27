"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

type Viewport = { x: number; y: number; scale: number };

// Capture before board controls or Konva can interpret a middle drag as an edit.
export function useCanvasMiddlePan(ref: RefObject<HTMLDivElement | null>, viewport: Viewport, onViewport: (value: Viewport) => void) {
  const latest = useRef({ viewport, onViewport });
  const [panning, setPanning] = useState(false);
  useLayoutEffect(() => { latest.current = { viewport, onViewport }; }, [viewport, onViewport]);
  // The overview swaps its host for the focused editor, so reattach on host changes.
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  const attach = useCallback((node: HTMLDivElement | null) => { ref.current = node; setHost(node); }, [ref]);
  useEffect(() => {
    if (!host) return;
    let drag: { id: number; x: number; y: number; viewport: Viewport } | null = null;
    const finish = (event: PointerEvent) => {
      if (!drag || event.pointerId !== drag.id) return;
      event.preventDefault(); event.stopPropagation();
      const id = drag.id; drag = null; setPanning(false);
      if (host.hasPointerCapture(id)) host.releasePointerCapture(id);
    };
    const down = (event: PointerEvent) => {
      if (event.button !== 1 || drag) return;
      event.preventDefault(); event.stopPropagation();
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY, viewport: latest.current.viewport };
      host.setPointerCapture(event.pointerId); setPanning(true);
    };
    const move = (event: PointerEvent) => {
      if (!drag || event.pointerId !== drag.id) return;
      event.preventDefault(); event.stopPropagation();
      latest.current.onViewport({ ...drag.viewport, x: drag.viewport.x + event.clientX - drag.x, y: drag.viewport.y + event.clientY - drag.y });
    };
    const suppress = (event: MouseEvent) => { if (event.button === 1) { event.preventDefault(); event.stopPropagation(); } };
    host.addEventListener("pointerdown", down, true);
    host.addEventListener("pointermove", move, true);
    host.addEventListener("pointerup", finish, true);
    host.addEventListener("pointercancel", finish, true);
    host.addEventListener("lostpointercapture", finish, true);
    host.addEventListener("mousedown", suppress, true);
    host.addEventListener("auxclick", suppress, true);
    return () => {
      const id = drag?.id; drag = null;
      if (id !== undefined && host.hasPointerCapture(id)) host.releasePointerCapture(id);
      host.removeEventListener("pointerdown", down, true);
      host.removeEventListener("pointermove", move, true);
      host.removeEventListener("pointerup", finish, true);
      host.removeEventListener("pointercancel", finish, true);
      host.removeEventListener("lostpointercapture", finish, true);
      host.removeEventListener("mousedown", suppress, true);
      host.removeEventListener("auxclick", suppress, true);
    };
  }, [host]);
  return { panning, attach };
}
