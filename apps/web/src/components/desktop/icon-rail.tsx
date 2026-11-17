"use client";
import { desktopApps, railApps, type AppId } from "@/lib/desktop-apps";
import type { DesktopWindow } from "@/lib/window-store";
import type { DariusMood } from "@/lib/types";
import { LiquidOrb } from "../liquid-orb";
import { appIcons, CanvasIcon, SettingsIcon } from "./icons";

/**
 * The desktop's app rail. A dot marks an open window; a hollow dot a minimized one.
 * "Canvas" minimizes every window to reveal the boards.
 */
export function IconRail({ windows, focused, mood, onApp, onCanvas, onHome }: {
  windows: DesktopWindow[]; focused: AppId | null; mood: DariusMood;
  onApp: (app: AppId) => void; onCanvas: () => void; onHome: () => void;
}) {
  const state = (app: AppId) => windows.find(window => window.app === app)?.mode;
  const item = (app: AppId) => {
    const Icon = appIcons[app], mode = state(app);
    return <button key={app} type="button" className={`dk-rail-app ${focused === app ? "is-focused" : ""} ${mode ? `is-${mode}` : ""}`} aria-label={desktopApps[app].title} aria-pressed={focused === app} title={desktopApps[app].title} onClick={() => onApp(app)}>
      <Icon size={20} />{mode ? <i aria-hidden="true" /> : null}
    </button>;
  };
  return <nav className="dk-rail" aria-label="Apps">
    <button type="button" className="dk-rail-home" aria-label="All projects" title="All projects" onClick={onHome}><LiquidOrb mood={mood} size="mark" /></button>
    <button type="button" className={`dk-rail-app dk-rail-canvas ${focused === null ? "is-focused" : ""}`} aria-label="Canvas" aria-pressed={focused === null} title="Canvas — show the boards" onClick={onCanvas}><CanvasIcon size={20} /></button>
    <span className="dk-rail-rule" aria-hidden="true" />
    <div className="dk-rail-apps">{railApps.map(item)}</div>
    <span className="dk-rail-spacer" aria-hidden="true" />
    <button type="button" className={`dk-rail-app ${focused === "settings" ? "is-focused" : ""} ${state("settings") ? `is-${state("settings")}` : ""}`} aria-label="Settings" title="Settings" onClick={() => onApp("settings")}><SettingsIcon size={19} />{state("settings") ? <i aria-hidden="true" /> : null}</button>
  </nav>;
}
