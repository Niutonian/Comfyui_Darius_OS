"use client";

import { MotionConfig, motion, useReducedMotion } from "motion/react";
import { ListVideo, Menu, MessageCircle, Minus, PanelRightOpen, Plus, Settings, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useHealth, useKnownJobs, useProjectAssets, useProjectEventStream, useProjectJobs, useProjectWorkflows, useProjects, useWorkflows } from "@/lib/queries";
import { gentleSpring } from "@/lib/os-motion";
import { readAppUrl, rememberAppUrl } from "@/lib/os-navigation";
import { useDariusStore } from "@/lib/store";
import { useMobileShell } from "@/lib/use-mobile-shell";
import type { ViewId } from "@/lib/types";
import { workspaceStatus } from "@/lib/workspace-status";
import { WorkspaceStatus } from "./workspace-status";
import { AssistantWorkspace } from "./assistant-workspace";
import { CreateView } from "./create-view";
import { EditView } from "./edit-view";
import { Inspector } from "./inspector";
import { JobTray } from "./job-tray";
import { MapView } from "./map-view";
import { ModeNavigation } from "./mode-navigation";
import { ProjectSelector } from "./project-selector";
import { AmbientBackground } from "./ambient-background";
import { LiquidOrb } from "./liquid-orb";
import { SettingsView } from "./settings-view";
import { HomeDesktop } from "./home-desktop";
import { DiagnosticConsole } from "./diagnostic-console";

const spaceCopy: Record<ViewId, [string, string]> = {
  home: ["HOME", "YOUR CREATIVE SPACE."],
  talk: ["TALK", "CHAT. PLAN. CREATE."],
  create: ["CREATE", "GENERATE. BROWSE. REVIEW."],
  map: ["MAP", "STRUCTURE. CONNECT. EXPLORE."],
  edit: ["EDIT", "ASSEMBLE. REFINE. DELIVER."],
  settings: ["SETTINGS", "TUNE YOUR SPACE."],
};

function windowTitle(view: ViewId, projectName: string | undefined) {
  if (view === "talk") return projectName ? `Darius — ${projectName}` : "Darius";
  if (view === "create") return "Create & Review";
  if (view === "map") return "World Map";
  if (view === "edit") return projectName ? `Edit — ${projectName}` : "Edit — Project Assembly";
  if (view === "settings") return "Settings";
  return "Darius";
}

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

export function AppShell() {
  const reduceMotion = useReducedMotion();
  const { view, theme, activeProjectId, knownJobIds, inspectorOpen, trayOpen, dariusMood, projects, setActiveProject, setInspectorOpen, setProjects, setTrayOpen, setView } = useDariusStore();
  const [voiceHost, setVoiceHost] = useState<HTMLDivElement | null>(null);
  const [editAssistantHost, setEditAssistantHost] = useState<HTMLDivElement | null>(null);
  const [editComposerHost, setEditComposerHost] = useState<HTMLDivElement | null>(null);
  const [editAssistantOpen, setEditAssistantOpen] = useState(false);
  const [canvasAssistantHost, setCanvasAssistantHost] = useState<HTMLDivElement | null>(null);
  const [canvasComposerHost, setCanvasComposerHost] = useState<HTMLDivElement | null>(null);
  const [canvasAssistantOpen, setCanvasAssistantOpen] = useState(false); const [canvasBoardContext, setCanvasBoardContext] = useState<import("@/lib/moss-workspace").SelectedBoardContext | null>(null);
  const [openStoryOnCreate, setOpenStoryOnCreate] = useState(false);
  const [homeSignal, setHomeSignal] = useState(0);
  const urlBoot = useRef(true);
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const dismissSheet = useCallback(() => { setInspectorOpen(false); setTrayOpen(false); setMobileNavigationOpen(false); }, [setInspectorOpen, setTrayOpen]);
  const mobile = useMobileShell(inspectorOpen ? "inspector" : trayOpen ? "jobs" : mobileNavigationOpen ? "navigation" : null, dismissSheet);
  const health = useHealth();
  const projectQuery = useProjects();
  const workflowQuery = useWorkflows();
  const projectWorkflowQuery = useProjectWorkflows(activeProjectId);
  const syncStatus = useProjectEventStream(activeProjectId);
  const knownJobs = useKnownJobs(knownJobIds);
  const projectJobQuery = useProjectJobs(activeProjectId);
  const projectJobs = useMemo(() => {
    const merged = new Map(
      [...knownJobs.jobs, ...(projectJobQuery.data ?? [])]
        .filter((job) => job.project_id === activeProjectId)
        .map((job) => [job.id, job]),
    );
    return Array.from(merged.values()).sort((left, right) => right.created_at.localeCompare(left.created_at));
  }, [activeProjectId, knownJobs.jobs, projectJobQuery.data]);
  const projectAssets = useProjectAssets(activeProjectId);
  const project = projects.find((item) => item.id === activeProjectId);
  const copy = spaceCopy[view];
  const status = workspaceStatus({ health: health.data, loading: health.isLoading, error: Boolean(health.error), sync: activeProjectId ? syncStatus : undefined, mood: dariusMood, jobs: projectJobs });
  const running = projectJobs.find((job) => job.status === "running" || job.status === "queued");

  useEffect(() => {
    if (projectQuery.data) setProjects(projectQuery.data);
  }, [projectQuery.data, setProjects]);

  useEffect(() => {
    if (inspectorOpen && trayOpen) setTrayOpen(false);
  }, [inspectorOpen, setTrayOpen, trayOpen]);

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

  return (
    <MotionConfig reducedMotion="user" transition={reduceMotion ? { duration: 0.12 } : gentleSpring}>
      <main className={`app-shell os-desktop theme-${theme} space-${view} ${inspectorOpen ? "with-inspector" : ""} ${running ? "has-active-job" : ""}`}>
        <AmbientBackground />
        <div className="space-label" aria-hidden="true"><strong>{copy[0]}</strong><span>{copy[1]}</span></div>
        <header className="topbar system-bar">
          <button className="mobile-navigation-launch icon-button" aria-label="Open navigation menu" aria-expanded={mobileNavigationOpen} onClick={() => setMobileNavigationOpen(true)} type="button"><Menu size={22} /></button>
          <ProjectSelector homeSignal={homeSignal} compact={mobile} />
          <button aria-label="Go to Darius home and choose a project" className="brand-lockup brand-home" onClick={goHome} title="Project desktop" type="button">
            <span className="brand-presence" title={status.label}><LiquidOrb mood={dariusMood} size="mark" /></span>
            <span className="wordmark">Darius</span>
            <span className="brand-caption">{view === "home" ? "Your personal creative space" : status.label}</span>
          </button>
          <div className="top-actions">
            <button aria-label="Open background jobs" aria-expanded={trayOpen} className="mobile-jobs-launch icon-button" onClick={() => { setInspectorOpen(false); setTrayOpen(!trayOpen); }} type="button"><ListVideo size={22} />{running ? <i /> : null}</button>
            <WorkspaceStatus health={health.data} loading={health.isLoading} error={Boolean(health.error)} sync={activeProjectId ? syncStatus : undefined} mood={dariusMood} jobs={projectJobs} onRefresh={() => void health.refetch()} />
            <button aria-current={view === "settings" ? "page" : undefined} aria-label="Open settings" className={`settings-launch ${view === "settings" ? "active" : ""}`} onClick={() => { rememberAppUrl("settings", activeProjectId, "push"); setView("settings"); }} title="Settings" type="button"><Settings size={17} /></button>
            <DiagnosticConsole projectId={activeProjectId} />
            <Clock />
            {!inspectorOpen ? <button aria-label="Open inspector" className="icon-button inspector-launch" onClick={() => setInspectorOpen(true)} type="button"><PanelRightOpen size={18} /></button> : null}
          </div>
        </header>
        <div className="workspace">
          <section className="main-stage desktop-surface">
            <header className="mobile-page-heading">
              <div><span>{view === "home" ? "DARIUS / YOUR CREATIVE SPACE" : project?.name ?? "DARIUS"}</span><h1>{view === "home" ? "Your studio" : view === "talk" ? "Darius" : view === "create" ? "Create" : view === "map" ? "World map" : view === "edit" ? "Edit" : "Settings"}</h1></div>
              {view === "home" ? <button className="primary-button" onClick={() => setHomeSignal((signal) => signal + 1)} type="button"><Plus size={20} />New project</button> : <span className={`mobile-presence tone-${status.tone}`}><i />{view === "talk" ? status.label : syncStatus === "live" ? "Synced" : "Your workspace"}</span>}
            </header>
            {view !== "home" && project ? <button className="project-presence" onClick={goHome} type="button">
              <span className="presence-folder" aria-hidden="true" />
              <strong>{project.name}</strong>
              <small>Desktop</small>
            </button> : null}
            {view === "home" ? <HomeDesktop onNewProject={() => setHomeSignal((signal) => signal + 1)} /> : null}
            {view !== "home" ? <motion.div className="app-window-surface" layoutId={activeProjectId ? `project-shell-${activeProjectId}` : "os-app-window"} /> : null}
            <div className={`app-frame ${view === "home" ? "is-home" : "is-app"}`}>
              {view !== "home" ? <header className="app-window-chrome os-chrome">
                <span className="os-chrome-dots" aria-hidden="true"><i /><i /><i /></span>
                <strong>{windowTitle(view, project?.name)}</strong>
                <span className="window-controls">
                  <button aria-label="Minimize application" onClick={goHome} title="Minimize to the dock" type="button"><Minus size={14} /></button>
                  <button aria-label="Close application" onClick={goHome} title="Close and return to the desktop" type="button"><X size={14} /></button>
                </span>
              </header> : null}
              <div className="app-window-body">
                {view === "create" ? <CreateView key={`create:${activeProjectId}`} initialStoryOpen={openStoryOnCreate} assets={projectAssets.data ?? []} hasError={projectAssets.isError} isLoading={projectAssets.isLoading} onCanvasBoardContext={setCanvasBoardContext} onCanvasComposerHost={setCanvasComposerHost} onCanvasAssistantHost={setCanvasAssistantHost} canvasAssistantOpen={canvasAssistantOpen} onToggleCanvasAssistant={() => setCanvasAssistantOpen(value => !value)} /> : null}
                {view === "map" ? <MapView onOrganizeStory={() => { setOpenStoryOnCreate(true); rememberAppUrl("create", activeProjectId, "push"); useDariusStore.getState().setView("create"); }} key={`map:${activeProjectId}`} assets={projectAssets.data ?? []} workflows={projectWorkflowQuery.data ?? []} /> : null}
                {view === "edit" ? <EditView key={`edit:${activeProjectId}`} assets={projectAssets.data ?? []} assistantOpen={!mobile && editAssistantOpen} onToggleAssistant={() => { if (mobile) { rememberAppUrl("talk", activeProjectId, "push"); setView("talk"); } else setEditAssistantOpen((open) => !open); }} onAssistantHost={setEditAssistantHost} onComposerHost={setEditComposerHost} /> : null}
                {view === "settings" ? <SettingsView key={`settings:${activeProjectId}`} /> : null}
                <AssistantWorkspace canvasBoard={view === "create" ? canvasBoardContext : null} compact={mobile} voiceHost={voiceHost} workspaceHost={view === "edit" ? editAssistantHost : view === "create" ? canvasAssistantHost : undefined} composerHost={view === "edit" ? editComposerHost : view === "create" ? canvasComposerHost : undefined} stayInView={view === "edit" || (view === "create" && Boolean(canvasComposerHost))} onInteract={() => { if (view === "create") setCanvasAssistantOpen(true); else setEditAssistantOpen(true); }} key={`assistant:${activeProjectId ?? "no-project"}`} projectId={activeProjectId} visible={view === "talk" || (view === "edit" && !mobile && editAssistantOpen && Boolean(editAssistantHost)) || (view === "create" && canvasAssistantOpen && Boolean(canvasAssistantHost))} workflows={workflowQuery.data ?? []} workflowsLoading={workflowQuery.isLoading} workflowsError={workflowQuery.error} onRetry={() => void workflowQuery.refetch()} />
              </div>
            </div>
          </section>
          <Inspector mobileModal={mobile} assets={projectAssets.data ?? []} jobs={projectJobs} workflows={projectWorkflowQuery.data ?? []} />
        </div>
        <div className={`bottom-controls ${mobile && mobileNavigationOpen ? "mobile-navigation-sheet" : ""}`} role={mobile && mobileNavigationOpen ? "dialog" : undefined} aria-modal={mobile && mobileNavigationOpen ? true : undefined} aria-label={mobile && mobileNavigationOpen ? "Navigation menu" : undefined}>
          <header className="mobile-sheet-title"><strong>Your workspace</strong><button className="icon-button" aria-label="Close navigation menu" onClick={() => setMobileNavigationOpen(false)} type="button"><X size={20} /></button></header>
          {mobile && mobileNavigationOpen ? <div className="mobile-navigation-status"><WorkspaceStatus health={health.data} loading={health.isLoading} error={Boolean(health.error)} sync={activeProjectId ? syncStatus : undefined} mood={dariusMood} jobs={projectJobs} onRefresh={() => void health.refetch()} /></div> : null}
          <ModeNavigation onNavigate={() => setMobileNavigationOpen(false)} /><div className="voice-controls-host" ref={setVoiceHost} />
        </div>
        {mobile && (inspectorOpen || trayOpen || mobileNavigationOpen) ? <button className="mobile-sheet-scrim" aria-label="Dismiss panel" onClick={dismissSheet} type="button" /> : null}
        {view !== "talk" && activeProjectId ? <button className="mobile-chat-fab" onClick={() => { rememberAppUrl("talk", activeProjectId, "push"); setView("talk"); }} type="button"><MessageCircle size={22} /><span>Ask Darius</span></button> : null}
        <JobTray mobileModal={mobile} hasError={knownJobs.hasError || projectJobQuery.isError} jobs={projectJobs} />
      </main>
    </MotionConfig>
  );
}
