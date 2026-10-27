"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import { History, Layers3, MessageCircle, X } from "lucide-react";
import type { CanvasHosts } from "./canvas-workspace";
import { MOBILE_MEDIA, useMobileSheetFocus } from "@/lib/use-mobile-shell";

const subscribe = (change: () => void) => { const media = window.matchMedia(MOBILE_MEDIA); media.addEventListener("change", change); return () => media.removeEventListener("change", change); };
export const useCanvasNarrow = () => useSyncExternalStore(subscribe, () => window.matchMedia(MOBILE_MEDIA).matches, () => false);

export type CanvasUtilityTab = "board" | "chat" | "history";

export function CanvasUtilityPanel({ open, tab, onTabChange, onClose, primaryLabel = "Board", context, primary, history, hosts }: {
  open: boolean; tab: CanvasUtilityTab; onTabChange: (tab: CanvasUtilityTab) => void; onClose: () => void;
  primaryLabel?: string; context: string; primary: ReactNode; history: ReactNode; hosts: CanvasHosts;
}) {
  const { assistantOpen, onToggleAssistant, onAssistantHost, onComposerHost } = hosts;
  const id = useId(), active = assistantOpen ? "chat" : tab;
  const narrow = useCanvasNarrow(), visible = open || Boolean(assistantOpen);
  const closeAction = useRef(() => {});
  useLayoutEffect(() => { closeAction.current = () => { if (assistantOpen) onToggleAssistant?.(); onClose(); }; }, [assistantOpen, onToggleAssistant, onClose]);
  const dismiss = useCallback(() => closeAction.current(), []);
  useMobileSheetFocus(narrow && visible ? ".canvas-utility-panel:not([hidden])" : null, dismiss);
  useEffect(() => {
    if (!narrow || !visible) return;
    const leave = (event: PointerEvent) => { if ((event.target as Element).closest(".mobile-navigation-launch,.mobile-jobs-launch,.settings-launch,.brand-home,.project-trigger")) dismiss(); };
    document.addEventListener("pointerdown", leave);
    return () => document.removeEventListener("pointerdown", leave);
  }, [narrow, visible, dismiss]);
  const tabs = [["board", primaryLabel, Layers3], ["chat", "Chat", MessageCircle], ["history", "History", History]] as const;
  function select(next: CanvasUtilityTab) {
    onTabChange(next);
    if (Boolean(assistantOpen) !== (next === "chat")) onToggleAssistant?.();
  }
  return <aside className="canvas-utility-panel" aria-label="Canvas utilities" role={narrow && visible ? "dialog" : undefined} aria-modal={narrow && visible ? true : undefined} hidden={!visible}>
    <header className="canvas-utility-header">
      <div role="tablist" aria-label="Canvas utility views" onKeyDown={event => {
        const index = tabs.findIndex(([key]) => key === active);
        const next = event.key === "Home" ? 0 : event.key === "End" ? 2 : event.key === "ArrowRight" ? (index + 1) % 3 : event.key === "ArrowLeft" ? (index + 2) % 3 : -1;
        if (next < 0) return;
        event.preventDefault(); event.stopPropagation(); select(tabs[next][0]);
        event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
      }}>{tabs.map(([key, label, Icon]) => <button key={key} id={`${id}-${key}`} type="button" role="tab" aria-selected={active === key} tabIndex={active === key ? 0 : -1} aria-controls={`${id}-${key}-content`} onClick={() => select(key)}><Icon size={15} /><span>{label}</span></button>)}</div>
      <button className="icon-button" aria-label="Close Canvas utilities" onClick={dismiss} type="button"><X size={16} /></button>
    </header>
    <section className="canvas-utility-content" role="tabpanel" id={`${id}-board-content`} aria-labelledby={`${id}-board`} hidden={active !== "board"}>{primary}</section>
    <section className="canvas-utility-content" role="tabpanel" id={`${id}-history-content`} aria-labelledby={`${id}-history`} hidden={active !== "history"}>{active === "history" ? history : null}</section>
    <section className="canvas-utility-chat" role="tabpanel" id={`${id}-chat-content`} aria-labelledby={`${id}-chat`} hidden={active !== "chat"}>
      <div className="canvas-chat-target"><MessageCircle size={14} /><div><strong>Project chat</strong><span>{context}</span></div></div>
      <div ref={onAssistantHost} className="canvas-assistant-host" />
      <div ref={onComposerHost} className="canvas-composer-host" />
    </section>
  </aside>;
}
