"use client";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

export type MenuItem = { label: string; hint?: string; icon?: ReactNode; disabled?: boolean; danger?: boolean; onSelect: () => void } | { separator: true; label?: string };

/**
 * A small right-click menu, positioned where the pointer was and kept on screen.
 * Arrow keys move, Enter chooses, Esc or a click elsewhere closes.
 */
export function ContextMenu({ x, y, label, items, onClose }: { x: number; y: number; label: string; items: MenuItem[]; onClose: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: x, top: y });
  useLayoutEffect(() => {
    const menu = root.current, host = menu?.offsetParent as HTMLElement | null;
    if (!menu || !host) return;
    const left = Math.max(8, Math.min(x, host.clientWidth - menu.offsetWidth - 8)), top = Math.max(8, Math.min(y, host.clientHeight - menu.offsetHeight - 8));
    setPosition(current => current.left === left && current.top === top ? current : { left, top });
    menu.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus({ preventScroll: true });
  }, [x, y]);
  useEffect(() => {
    const away = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) onClose(); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); } };
    document.addEventListener("pointerdown", away, true); window.addEventListener("keydown", escape, true); window.addEventListener("blur", onClose);
    return () => { document.removeEventListener("pointerdown", away, true); window.removeEventListener("keydown", escape, true); window.removeEventListener("blur", onClose); };
  }, [onClose]);
  function keys(event: React.KeyboardEvent) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const buttons = [...(root.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [])];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next]?.focus();
  }
  return <div ref={root} className="dk-context-menu" role="menu" aria-label={label} style={position} onKeyDown={keys} onContextMenu={event => event.preventDefault()}>
    {items.map((item, index) => "separator" in item
      ? item.label ? <span key={index} className="dk-menu-label">{item.label}</span> : <i key={index} aria-hidden="true" />
      : <button key={index} type="button" role="menuitem" disabled={item.disabled} className={item.danger ? "is-danger" : ""} onClick={() => { onClose(); item.onSelect(); }}>
        {item.icon}<span>{item.label}</span>{item.hint ? <small>{item.hint}</small> : null}
      </button>)}
  </div>;
}
