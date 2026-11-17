import { create } from "zustand";
import { persist } from "zustand/middleware";
import { desktopApps, type AppId } from "./desktop-apps";

export type WindowMode = "normal" | "minimized" | "maximized";
export type DesktopWindow = { app: AppId; x: number; y: number; w: number; h: number; z: number; mode: WindowMode };
export type Viewport = { width: number; height: number };
type Rect = Pick<DesktopWindow, "x" | "y" | "w" | "h">;

/** Space the shell keeps clear: the icon rail on the left and the system bar on top. */
export const DESKTOP_INSET = { left: 96, top: 20, right: 20, bottom: 20 };
export const MIN_WINDOW = { w: 360, h: 260 };
const GRAB = 96;

/** Keep a window sized to fit and its title bar reachable. */
export function clampWindow(rect: Rect, viewport: Viewport): Rect {
  const maxW = Math.max(MIN_WINDOW.w, viewport.width - DESKTOP_INSET.left - DESKTOP_INSET.right);
  const maxH = Math.max(MIN_WINDOW.h, viewport.height - DESKTOP_INSET.top - DESKTOP_INSET.bottom);
  const w = Math.round(Math.min(maxW, Math.max(MIN_WINDOW.w, rect.w)));
  const h = Math.round(Math.min(maxH, Math.max(MIN_WINDOW.h, rect.h)));
  const x = Math.round(Math.min(viewport.width - GRAB, Math.max(DESKTOP_INSET.left - w + GRAB, rect.x)));
  const y = Math.round(Math.min(viewport.height - 48, Math.max(DESKTOP_INSET.top, rect.y)));
  return { x, y, w, h };
}

/** New windows cascade from the top-left of the free area. */
export function cascade(open: DesktopWindow[], size: { w: number; h: number }, viewport: Viewport): Rect {
  const step = 32 * (open.filter(window => window.mode !== "minimized").length % 6);
  return clampWindow({ x: DESKTOP_INSET.left + 40 + step, y: DESKTOP_INSET.top + 56 + step, ...size }, viewport);
}

export function focusedWindow(windows: DesktopWindow[]) {
  return windows.filter(window => window.mode !== "minimized").sort((a, b) => b.z - a.z)[0] ?? null;
}

function topZ(windows: DesktopWindow[]) { return windows.reduce((z, window) => Math.max(z, window.z), 0) + 1; }
/** Renumber z so it stays small and ordered after many focus changes. */
function normalise(windows: DesktopWindow[]) {
  const order = [...windows].sort((a, b) => a.z - b.z).map(window => window.app);
  return windows.map(window => ({ ...window, z: order.indexOf(window.app) + 1 }));
}

type WindowStore = {
  /** Windows per scope: a project id, or "home" for the launcher. */
  scopes: Record<string, DesktopWindow[]>;
  open: (scope: string, app: AppId, viewport: Viewport) => void;
  focus: (scope: string, app: AppId) => void;
  minimize: (scope: string, app: AppId) => void;
  toggleMaximize: (scope: string, app: AppId) => void;
  close: (scope: string, app: AppId) => void;
  place: (scope: string, app: AppId, rect: Rect, viewport: Viewport) => void;
  minimizeAll: (scope: string) => void;
};

export const useWindowStore = create<WindowStore>()(persist((set) => {
  const update = (scope: string, change: (windows: DesktopWindow[]) => DesktopWindow[]) =>
    set(state => ({ scopes: { ...state.scopes, [scope]: normalise(change(state.scopes[scope] ?? [])) } }));
  return {
    scopes: {},
    open: (scope, app, viewport) => update(scope, windows => {
      const existing = windows.find(window => window.app === app);
      const z = topZ(windows);
      if (existing) return windows.map(window => window.app === app ? { ...window, z, mode: window.mode === "minimized" ? (desktopApps[app].maximized ? "maximized" : "normal") : window.mode } : window);
      const meta = desktopApps[app];
      return [...windows, { app, ...cascade(windows, meta.size, viewport), z, mode: meta.maximized ? "maximized" : "normal" }];
    }),
    focus: (scope, app) => update(scope, windows => {
      const target = windows.find(window => window.app === app);
      if (!target || (target.z === topZ(windows) - 1 && target.mode !== "minimized")) return windows;
      const z = topZ(windows);
      return windows.map(window => window.app === app ? { ...window, z, mode: window.mode === "minimized" ? "normal" : window.mode } : window);
    }),
    minimize: (scope, app) => update(scope, windows => windows.map(window => window.app === app ? { ...window, mode: "minimized" } : window)),
    toggleMaximize: (scope, app) => update(scope, windows => {
      const z = topZ(windows);
      return windows.map(window => window.app === app ? { ...window, z, mode: window.mode === "maximized" ? "normal" : "maximized" } : window);
    }),
    close: (scope, app) => update(scope, windows => windows.filter(window => window.app !== app)),
    place: (scope, app, rect, viewport) => update(scope, windows => windows.map(window => window.app === app ? { ...window, ...clampWindow(rect, viewport) } : window)),
    minimizeAll: scope => update(scope, windows => windows.map(window => ({ ...window, mode: "minimized" }))),
  };
}, { name: "darius-windows-v1", version: 1 }));
