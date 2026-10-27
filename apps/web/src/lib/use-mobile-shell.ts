"use client";

import { useEffect, useSyncExternalStore } from "react";

export const MOBILE_MEDIA = "(max-width: 760px), (max-width: 1000px) and (max-height: 500px)";
function subscribe(change: () => void) {
  const media = window.matchMedia(MOBILE_MEDIA);
  media.addEventListener("change", change);
  return () => media.removeEventListener("change", change);
}
const snapshot = () => window.matchMedia(MOBILE_MEDIA).matches;
const serverSnapshot = () => false;

/** VisualViewport follows Android's keyboard without remounting the voice/chat tree. */
export function useMobileShell(panel: "jobs" | "inspector" | "navigation" | null, dismiss: () => void) {
  const mobile = useSyncExternalStore(subscribe, snapshot, serverSnapshot);
  useEffect(() => {
    if (!mobile) return;
    const root = document.documentElement;
    const viewport = window.visualViewport;
    let baseline = viewport?.height ?? window.innerHeight;
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const height = viewport?.height ?? window.innerHeight;
        const editing = document.activeElement?.matches('textarea, input:not([type="checkbox"]):not([type="radio"]):not([type="range"])');
        if (!editing) baseline = height;
        root.style.setProperty("--darius-viewport-height", height + "px");
        root.style.setProperty("--darius-viewport-top", (viewport?.offsetTop ?? 0) + "px");
        root.dataset.mobileKeyboard = String(Boolean(editing && baseline - height > 120));
      });
    };
    update();
    viewport?.addEventListener("resize", update);
    viewport?.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    document.addEventListener("focusin", update);
    document.addEventListener("focusout", update);
    return () => {
      cancelAnimationFrame(frame);
      viewport?.removeEventListener("resize", update);
      viewport?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      document.removeEventListener("focusin", update);
      document.removeEventListener("focusout", update);
      root.style.removeProperty("--darius-viewport-height");
      root.style.removeProperty("--darius-viewport-top");
      delete root.dataset.mobileKeyboard;
    };
  }, [mobile]);
  useMobileSheetFocus(mobile && panel ? panel === "jobs" ? ".job-tray.open" : panel === "navigation" ? ".mobile-navigation-sheet" : ".inspector" : null, dismiss);
  return mobile;
}

export function useMobileSheetFocus(selector: string | null, dismiss: () => void) {
  useEffect(() => {
    if (!selector) return;
    const sheet = document.querySelector<HTMLElement>(selector);
    if (!sheet) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const controls = () => [...sheet.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')]
      .filter((item) => item.getClientRects().length);
    const frame = requestAnimationFrame(() => {
      const close = sheet.querySelector<HTMLElement>('button[aria-label^="Close"]');
      (close ?? controls()[0])?.focus({ preventScroll: true });
    });
    const key = (event: KeyboardEvent) => {
      if (document.querySelector("dialog[open], .fullscreen-voice")) return;
      if (event.key === "Escape") { event.preventDefault(); dismiss(); }
      if (event.key !== "Tab") return;
      const items = controls(), first = items[0], last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", key);
    return () => { cancelAnimationFrame(frame); document.removeEventListener("keydown", key); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, [selector, dismiss]);
}
