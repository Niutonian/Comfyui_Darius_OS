"use client";
import { useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { desktopApps } from "@/lib/desktop-apps";
import type { DesktopWindow as WindowState } from "@/lib/window-store";
import { appIcons, CloseIcon, MaximizeIcon, MinimizeIcon, RestoreIcon } from "./icons";

type Rect = { x: number; y: number; w: number; h: number };

/**
 * A movable, resizable window over the canvas. Minimized windows stay mounted (hidden)
 * so an open edit, a chat draft or a scroll position survives.
 */
export function DesktopWindow({ window: state, focused, onFocus, onMinimize, onToggleMaximize, onClose, onPlace, children }: {
  window: WindowState; focused: boolean; children: ReactNode;
  onFocus: () => void; onMinimize: () => void; onToggleMaximize: () => void; onClose: () => void; onPlace: (rect: Rect) => void;
}) {
  const meta = desktopApps[state.app], Icon = appIcons[state.app];
  const [draft, setDraft] = useState<Rect | null>(null);
  const gesture = useRef<{ id: number; kind: "move" | "resize"; x: number; y: number; start: Rect } | null>(null);
  const rect = draft ?? state;
  const maximized = state.mode === "maximized";

  function begin(event: ReactPointerEvent<HTMLElement>, kind: "move" | "resize") {
    if (event.button !== 0 || maximized) return;
    if (kind === "move" && (event.target as Element).closest("button")) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current = { id: event.pointerId, kind, x: event.clientX, y: event.clientY, start: { x: state.x, y: state.y, w: state.w, h: state.h } };
  }
  function move(event: ReactPointerEvent<HTMLElement>) {
    const g = gesture.current; if (!g || g.id !== event.pointerId) return;
    const dx = event.clientX - g.x, dy = event.clientY - g.y;
    setDraft(g.kind === "move" ? { ...g.start, x: g.start.x + dx, y: g.start.y + dy } : { ...g.start, w: g.start.w + dx, h: g.start.h + dy });
  }
  function end(event: ReactPointerEvent<HTMLElement>) {
    const g = gesture.current; if (!g || g.id !== event.pointerId) return;
    gesture.current = null;
    if (draft) onPlace(draft);
    setDraft(null);
  }

  return <section className={`dk-window app-${state.app} ${maximized ? "is-maximized" : ""} ${focused ? "is-focused" : ""} ${draft ? "is-dragging" : ""}`}
    role="region" aria-label={`${meta.title} window`} hidden={state.mode === "minimized"}
    style={{ "--x": `${rect.x}px`, "--y": `${rect.y}px`, "--w": `${rect.w}px`, "--h": `${rect.h}px`, zIndex: 20 + state.z } as CSSProperties}
    onPointerDownCapture={onFocus}>
    <header className="dk-window-bar" onPointerDown={event => begin(event, "move")} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onDoubleClick={event => { if (!(event.target as Element).closest("button")) onToggleMaximize(); }}>
      <span className="dk-window-icon"><Icon size={16} /></span>
      <strong>{meta.title}</strong>
      <span className="dk-window-controls">
        <button type="button" aria-label={`Minimize ${meta.title}`} title="Minimize to the rail" onClick={onMinimize}><MinimizeIcon size={15} /></button>
        <button type="button" aria-label={maximized ? `Restore ${meta.title}` : `Maximize ${meta.title}`} title={maximized ? "Restore size" : "Fill the desktop"} onClick={onToggleMaximize}>{maximized ? <RestoreIcon size={14} /> : <MaximizeIcon size={14} />}</button>
        <button type="button" aria-label={`Close ${meta.title}`} title="Close" onClick={onClose}><CloseIcon size={15} /></button>
      </span>
    </header>
    <div className="dk-window-body">{children}</div>
    {!maximized ? <span className="dk-window-resize" aria-hidden="true" onPointerDown={event => begin(event, "resize")} onPointerMove={move} onPointerUp={end} onPointerCancel={end} /> : null}
  </section>;
}
