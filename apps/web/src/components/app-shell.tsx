"use client";

import { MotionConfig, useReducedMotion } from "motion/react";
import { ListVideo, PanelRightOpen } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useHealth, useProjectAssets, useProjectEventStream, useProjectJobs, useProjectWorkflows, useProjects, useWorkflows } from "@/lib/queries";
import { gentleSpring } from "@/lib/os-motion";
import { readAppUrl, rememberAppUrl } from "@/lib/os-navigation";
import { useDariusStore } from "@/lib/store";
import { useMobileShell } from "@/lib/use-mobile-shell";
import { appForView, desktopApps, type AppId } from "@/lib/desktop-apps";
import { focusedWindow, useWindowStore } from "@/lib/window-store";
import type { SelectedBoardContext } from "@/lib/moss-workspace";
import { useWorkspaceState } from "@/lib/workspace-session";
import { WorkspaceStatus } from "./workspace-status";
import { AssistantWorkspace } from "./assistant-workspace";
import { Inspector } from "./inspector";
import { JobTray } from "./job-tray";
import { ProjectSelector } from "./project-selector";
import { AmbientBackground } from "./ambient-background";
import { HomeDesktop } from "./home-desktop";
import { DiagnosticConsole } from "./diagnostic-console";
import { MossWorkspace } from "./moss-workspace";
import { IconRail } from "./desktop/icon-rail";
import { DesktopWindow } from "./desktop/desktop-window";
import { AppContent, type AppContext } from "./desktop/app-content";
import { WindowBoundary } from "./desktop/window-boundary";
import { WidgetColumn } from "./desktop/widget-column";
import { DotWord } from "./desktop/dot-word";
import { SettingsIcon } from "./desktop/icons";

function Clock() {
  const [label, setLabel] = useState("");
  useEffect(() => {
    const tick = () => setLabel(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
    const first = window.setTimeout(tick, 0);
    const timer = window.setInterval(tick, 30_000);
    return () => { window.clearTimeout(first); window.clearInterval(timer); };
  }, []);
  return <time className="system-clock">{label}</time>;
}

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight });
const NO_WINDOWS: never[] = [];

/**
 * Darius as a desktop. With a project open, its canvas is the desktop surface and every
 * other tool is a window over it. Without one, the launcher lists projects.
 */
export function AppShell() {
  const reduceMotion = useReducedMotion();
  const { view, theme, activeProjectId, inspectorOpen, trayOpen, dariusMood, setActiveProject, setInspectorOpen, setProjects, setTrayOpen, setView } = useDariusStore();
  // Slots the shell-owned conversation and the canvas portal into.
  const [voiceHost, setVoiceHost] = useState<HTMLDivElement | null>(null);
  const [quickHost, setQuickHost] = useState<HTMLDivElement | null>(null);
  const [homeHost, setHomeHost] = useState<HTMLDivElement | null>(null);
  const [conversationHost, setConversationHost] = useState<HTMLDivElement | null>(null);
  const [composerHost, setComposerHost] = useState<HTMLDivElement | null>(null);
  const [panelHost, setPanelHost] = useState<HTMLDivElement | null>(null);
  const [canvasBoard, setCanvasBoard] = useState<SelectedBoardContext | null>(null);
  const [columnOpen, setColumnOpen] = useWorkspaceState("desktop:column", true);
  const [homeSignal, setHomeSignal] = useState(0);
  const urlBoot = useRef(true);
  const dismissSheet = useCallback(() => { setInspectorOpen(false); setTrayOpen(false); }, [setInspectorOpen, setTrayOpen]);
  const mobile = useMobileShell(inspectorOpen ? "inspector" : trayOpen ? "jobs" : null, dismissSheet);
  const health = useHealth();
  const projectQuery = useProjects();
  const workflowQuery = useWorkflows();
  const projectWorkflowQuery = useProjectWorkflows(activeProjectId);
  const syncStatus = useProjectEventStream(activeProjectId);
  const projectJobQuery = useProjectJobs(activeProjectId);
  // The project endpoint already returns its full job history. Hydrating every
  // persisted job ID duplicates it and fans out reads across unrelated projects.
  const projectJobs = useMemo(() => (projectJobQuery.data ?? [])
    .filter(job => job.project_id === activeProjectId)
    .sort((left, right) => right.created_at.localeCompare(left.created_at)), [activeProjectId, projectJobQuery.data]);
  const projectAssets = useProjectAssets(activeProjectId);
  const running = projectJobs.find((job) => job.status === "running" || job.status === "queued");

  const onDesktop = view !== "home" && Boolean(activeProjectId);
  const scope = onDesktop ? activeProjectId! : "home";
  const windows = useWindowStore(state => state.scopes[scope] ?? NO_WINDOWS);
  const windowActions = useWindowStore.getState;
  const focused = focusedWindow(windows);
  const chat = windows.find(window => window.app === "chat");
  const chatVisible = onDesktop && Boolean(chat && chat.mode !== "minimized");

  /** Open (or raise) an app. Focusing a window names it in the URL. */
  const openApp = useCallback((app: AppId) => {
    if (desktopApps[app].project && !onDesktop) return;
    windowActions().open(scope, app, viewport());
    if (onDesktop) setView(desktopApps[app].view);
  }, [onDesktop, scope, setView, windowActions]);
  const settle = useCallback(() => {
    const next = focusedWindow(useWindowStore.getState().scopes[scope] ?? []);
    if (onDesktop) setView(next ? desktopApps[next.app].view : "create");
  }, [onDesktop, scope, setView]);

  useEffect(() => {
    if (projectQuery.data) setProjects(projectQuery.data);
  }, [projectQuery.data, setProjects]);

  useEffect(() => {
    if (inspectorOpen && trayOpen) setTrayOpen(false);
  }, [inspectorOpen, setTrayOpen, trayOpen]);

  // A view that names an app (from the URL, history, or "Use with Darius") opens it.
  useEffect(() => {
    const app = appForView(view);
    if (app && onDesktop) windowActions().open(scope, app, viewport());
  }, [view, onDesktop, scope, windowActions]);

  useEffect(() => {
    if (urlBoot.current) {
      urlBoot.current = false;
      const url = readAppUrl();
      const viewChanged = Boolean(url.view && url.view !== view);
      const projectChanged = Boolean(url.projectId && url.projectId !== activeProjectId);
      if (viewChanged && url.view) setView(url.view);
      if (projectChanged && url.projectId) setActiveProject(url.projectId);
      if (viewChanged || projectChanged) return;
    }
    rememberAppUrl(view, activeProjectId, "replace");
  }, [activeProjectId, setActiveProject, setView, view]);

  useEffect(() => {
    const apply = () => {
      const url = readAppUrl();
      if (url.view) setView(url.view);
      if (url.projectId) setActiveProject(url.projectId);
    };
    window.addEventListener("popstate", apply);
    return () => window.removeEventListener("popstate", apply);
  }, [setActiveProject, setView]);

  function goHome() {
    rememberAppUrl("home", activeProjectId, "push");
    setView("home");
    setInspectorOpen(false);
  }
  function showCanvas() {
    windowActions().minimizeAll(scope);
    setView("create");
  }

  const appContext: AppContext = {
    projectId: activeProjectId, assets: projectAssets.data ?? [], assetsLoading: projectAssets.isLoading, assetsError: projectAssets.isError,
    workflows: projectWorkflowQuery.data ?? [], openApp,
  };
  const status = <WorkspaceStatus health={health.data} loading={health.isLoading} error={Boolean(health.error)} sync={activeProjectId ? syncStatus : undefined} mood={dariusMood} jobs={projectJobs} onRefresh={() => void health.refetch()} />;
  const systemCluster = <div className="dk-system">
    <button aria-label="Open background jobs" aria-expanded={trayOpen} className="dk-system-jobs icon-button" onClick={() => { setInspectorOpen(false); setTrayOpen(!trayOpen); }} type="button"><ListVideo size={17} />{running ? <i /> : null}</button>
    {status}
    <DiagnosticConsole projectId={activeProjectId} />
    <Clock />
    {!inspectorOpen ? <button aria-label="Open inspector" className="icon-button inspector-launch" onClick={() => setInspectorOpen(true)} type="button"><PanelRightOpen size={17} /></button> : null}
  </div>;

  return (
    <MotionConfig reducedMotion="user" transition={reduceMotion ? { duration: 0.12 } : gentleSpring}>
      <main className={`app-shell os-desktop dk-shell theme-${theme} ${onDesktop ? "space-desktop" : "space-home"} ${focused ? `focus-${focused.app}` : ""} ${columnOpen ? "" : "column-collapsed"} ${running ? "has-active-job" : ""}`}>
        {onDesktop ? <div className="dk-desktop">
          <IconRail windows={windows} focused={focused?.app ?? null} mood={dariusMood} onHome={goHome} onCanvas={showCanvas}
            onApp={app => { const current = windows.find(window => window.app === app); if (current && focused?.app === app) { windowActions().minimize(scope, app); settle(); } else openApp(app); }} />
          <div className="dk-stage">
            <header className="dk-topbar">
              <div className="dk-project-chip"><ProjectSelector homeSignal={homeSignal} compact={mobile} /></div>
              {systemCluster}
            </header>
            <MossWorkspace key={activeProjectId} projectId={activeProjectId!} assets={projectAssets.data ?? []} onBoardContext={setCanvasBoard} panelHost={panelHost} />
          </div>
          <WidgetColumn projectId={activeProjectId!} assets={projectAssets.data ?? []} jobs={projectJobs} mood={dariusMood} open={columnOpen} boardSelected={Boolean(canvasBoard)} chatOpen={chatVisible}
            onToggle={() => setColumnOpen(open => !open)} onApp={openApp} onJobs={() => { setInspectorOpen(false); setTrayOpen(true); }}
            onPanelHost={setPanelHost} onVoiceHost={setVoiceHost} onComposerHost={setQuickHost} />
        </div> : <div className="dk-launcher">
          <AmbientBackground />
          <header className="dk-topbar">
            <div className="dk-brand"><DotWord text="Darius" height={22} /><span>Your creative space</span></div>
            <div className="dk-launcher-actions"><ProjectSelector homeSignal={homeSignal} compact={mobile} /><button type="button" className="icon-button" aria-label="Settings" onClick={() => openApp("settings")}><SettingsIcon size={18} /></button></div>
            {systemCluster}
          </header>
          <HomeDesktop onNewProject={() => setHomeSignal((signal) => signal + 1)} />
          <div className="dk-launcher-composer" ref={setHomeHost} />
        </div>}
        <div className="dk-windows">
          {windows.map(window => <DesktopWindow key={`${scope}:${window.app}`} window={window} focused={focused?.app === window.app}
            onFocus={() => { if (focused?.app !== window.app) { windowActions().focus(scope, window.app); if (onDesktop) setView(desktopApps[window.app].view); } }}
            onMinimize={() => { windowActions().minimize(scope, window.app); settle(); }}
            onToggleMaximize={() => windowActions().toggleMaximize(scope, window.app)}
            onClose={() => { windowActions().close(scope, window.app); settle(); }}
            onPlace={rect => windowActions().place(scope, window.app, rect, viewport())}>
            <WindowBoundary title={desktopApps[window.app].title} onClose={() => { windowActions().close(scope, window.app); settle(); }}>
              <AppContent app={window.app} context={appContext} onConversationHost={setConversationHost} onComposerHost={setComposerHost} />
            </WindowBoundary>
          </DesktopWindow>)}
        </div>
        <AssistantWorkspace key={`assistant:${activeProjectId ?? "no-project"}`} projectId={activeProjectId} compact={mobile}
          visible={chatVisible} canvasBoard={onDesktop ? canvasBoard : null}
          voiceHost={onDesktop ? voiceHost : undefined}
          workspaceHost={chatVisible ? conversationHost : undefined}
          composerHost={chatVisible ? composerHost : onDesktop ? quickHost : homeHost}
          stayInView={onDesktop} onInteract={() => openApp("chat")}
          workflows={workflowQuery.data ?? []} workflowsLoading={workflowQuery.isLoading} workflowsError={workflowQuery.error} onRetry={() => void workflowQuery.refetch()} />
        <Inspector mobileModal={mobile} assets={projectAssets.data ?? []} jobs={projectJobs} workflows={projectWorkflowQuery.data ?? []} />
        {mobile && (inspectorOpen || trayOpen) ? <button className="mobile-sheet-scrim" aria-label="Dismiss panel" onClick={dismissSheet} type="button" /> : null}
        <JobTray mobileModal={mobile} hasError={projectJobQuery.isError} jobs={projectJobs} />
      </main>
    </MotionConfig>
  );
}
