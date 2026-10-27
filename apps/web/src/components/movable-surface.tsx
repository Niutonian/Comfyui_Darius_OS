"use client";
import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Reparent one stable portal container, preserving composer state instead of remounting it. */
export function MovableSurface({ target, children }: { target?: HTMLElement | null; children: ReactNode }) {
  const [holder, setHolder] = useState<HTMLDivElement | null>(null);
  const [fallback, setFallback] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = document.createElement("div"); element.className = "composer-surface";
    // Container creation is a browser resource; children mount only after it exists.
    const frame = requestAnimationFrame(() => setHolder(element));
    return () => { cancelAnimationFrame(frame); element.remove(); };
  }, []);
  useEffect(() => {
    const destination = target ?? fallback;
    if (!destination || !holder) return;
    const focused = document.activeElement instanceof HTMLElement && holder.contains(document.activeElement) ? document.activeElement : null;
    const selection = focused instanceof HTMLTextAreaElement ? [focused.selectionStart, focused.selectionEnd] : null;
    destination.appendChild(holder);
    if (focused) { focused.focus({ preventScroll: true }); if (focused instanceof HTMLTextAreaElement && selection) focused.setSelectionRange(selection[0], selection[1]); }
  }, [target, fallback, holder]);
  return <><div className="composer-surface" ref={setFallback} />{holder ? createPortal(children, holder) : null}</>;
}
