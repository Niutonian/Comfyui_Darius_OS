"use client";
/* eslint-disable @next/next/no-img-element -- project covers are local API files */

import { motion } from "motion/react";
import { useQueries } from "@tanstack/react-query";
import { FolderOpen, Info, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { api } from "@/lib/api-client";
import { desktopColumns, moveId, orderProjects, snapIndex, useDesktopOrder } from "@/lib/desktop-layout";
import { rememberAppUrl } from "@/lib/os-navigation";
import { queryKeys } from "@/lib/queries";
import { useDariusStore } from "@/lib/store";
import { MOBILE_MEDIA } from "@/lib/use-mobile-shell";
import type { Asset, Project, Scene } from "@/lib/types";
import { useWorkspaceScroll, useWorkspaceState } from "@/lib/workspace-session";

function coverAsset(assets: Asset[] | undefined) {
  return assets?.find((asset) => asset.kind === "image" && asset.role !== "derivative");
}

function tabIndex(id: string) {
  return [...id].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 5;
}

function FolderFace({ project, cover, meta, tab }: { project: Project; cover?: Asset; meta: string; tab: number }) {
  return <>
    <span className={`folder-tab folder-tab-${tab}`} />
    <span className="folder-body">
      <span className="folder-cover">{cover ? <img alt="" src={api.assetContentUrl(cover.id)} /> : <span>{project.name.slice(0, 1).toUpperCase()}</span>}</span>
      <strong>{project.name}</strong>
      <small>{meta}</small>
    </span>
  </>;
}

export function HomeDesktop({ onNewProject }: { onNewProject: () => void }) {
  const { projects, activeProjectId, setSelection, setInspectorOpen, openProject } = useDariusStore();
  const [selectedProject, setSelectedProject] = useWorkspaceState<string | null>("home:selection", activeProjectId);
  const desktop = useRef<HTMLElement>(null);
  useWorkspaceScroll("home:scroll", desktop);
  const order = useDesktopOrder((state) => state.order);
  const setOrder = useDesktopOrder((state) => state.setOrder);
  const sorted = useMemo(() => orderProjects(projects, order), [projects, order]);
  const gridRef = useRef<HTMLDivElement>(null);
  const suppressClick = useRef(false);
  const [columns, setColumns] = useState(4);
  const [drag, setDrag] = useState<{ id: string; x: number; y: number; index: number } | null>(null);
  const assetQueries = useQueries({
    queries: projects.map((project) => ({
      queryKey: queryKeys.projectAssets(project.id),
      queryFn: () => api.assets({ project_id: project.id, limit: 12 }),
      staleTime: 30_000,
    })),
  });
  const sceneQueries = useQueries({
    queries: projects.map((project) => ({
      queryKey: queryKeys.scenes(project.id),
      queryFn: () => api.scenes(project.id),
      staleTime: 30_000,
    })),
  });
  const assetById = new Map(projects.map((project, index) => [project.id, assetQueries[index]?.data]));
  const sceneById = new Map(projects.map((project, index) => [project.id, sceneQueries[index]?.data as Scene[] | undefined]));

  useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    const measure = () => {
      const style = getComputedStyle(grid);
      const cell = parseFloat(style.getPropertyValue("--folder-w")) || 190;
      const gap = parseFloat(style.getPropertyValue("--folder-gap-x")) || 54;
      const next = desktopColumns(grid.clientWidth, cell, gap);
      grid.style.setProperty("--desktop-columns", String(next));
      setColumns(next);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    return () => observer.disconnect();
  }, [sorted.length]);

  function open(projectId: string) {
    const nextView = useDariusStore.getState().lastView;
    const view = nextView === "home" || nextView === "settings" ? "talk" : nextView;
    rememberAppUrl(view, projectId, "push");
    openProject(projectId);
  }

  function metaFor(project: Project) {
    const assets = assetById.get(project.id);
    const scenes = sceneById.get(project.id);
    const assetCount = assets?.length;
    const sceneCount = scenes?.length;
    return assetCount !== undefined && sceneCount !== undefined
      ? `${assetCount} ${assetCount === 1 ? "asset" : "assets"} · ${sceneCount} ${sceneCount === 1 ? "scene" : "scenes"}`
      : (project.visual_style || project.description || "Creative project");
  }

  function indexAt(clientX: number, clientY: number) {
    const grid = gridRef.current;
    if (!grid) return 0;
    const style = getComputedStyle(grid);
    const cellW = parseFloat(style.getPropertyValue("--folder-w")) || 190;
    const cellH = parseFloat(style.getPropertyValue("--folder-h")) || 248;
    const gapX = parseFloat(style.getPropertyValue("--folder-gap-x")) || 54;
    const gapY = parseFloat(style.getPropertyValue("--folder-gap-y")) || 42;
    const rect = grid.getBoundingClientRect();
    const padLeft = parseFloat(style.paddingLeft) || 0;
    const padRight = parseFloat(style.paddingRight) || 0;
    const padTop = parseFloat(style.paddingTop) || 0;
    const contentWidth = rect.width - padLeft - padRight;
    const used = columns * cellW + Math.max(0, columns - 1) * gapX;
    const originX = rect.left + padLeft + (contentWidth - used) / 2;
    return snapIndex(clientX - originX, clientY - (rect.top + padTop), columns, sorted.length, cellW, cellH, gapX, gapY);
  }

  function nudge(id: string, key: string) {
    const ids = sorted.map((project) => project.id);
    const index = ids.indexOf(id);
    const delta = key === "ArrowLeft" ? -1 : key === "ArrowRight" ? 1 : key === "ArrowUp" ? -columns : columns;
    const next = index + delta;
    if (index < 0 || next < 0 || next >= ids.length) return;
    setOrder(moveId(ids, id, next));
  }

  function beginDrag(event: ReactPointerEvent, id: string) {
    if (event.pointerType === "touch" || window.matchMedia(MOBILE_MEDIA).matches) return;
    if (event.button !== 0) return;
    const startX = event.clientX;
    const startY = event.clientY;
    const pointerId = event.pointerId;
    let active = false;
    function finish(clientX: number, clientY: number, commit: boolean) {
      if (active && commit) setOrder(moveId(sorted.map((project) => project.id), id, indexAt(clientX, clientY)));
      setDrag(null);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
    }
    function move(pointerEvent: PointerEvent) {
      if (pointerEvent.pointerId !== pointerId) return;
      if (!active && Math.hypot(pointerEvent.clientX - startX, pointerEvent.clientY - startY) < 8) return;
      active = true;
      suppressClick.current = true;
      setDrag({ id, x: pointerEvent.clientX, y: pointerEvent.clientY, index: indexAt(pointerEvent.clientX, pointerEvent.clientY) });
    }
    function up(pointerEvent: PointerEvent) {
      if (pointerEvent.pointerId !== pointerId) return;
      finish(pointerEvent.clientX, pointerEvent.clientY, true);
    }
    function cancel(pointerEvent: PointerEvent) {
      if (pointerEvent.pointerId !== pointerId) return;
      finish(pointerEvent.clientX, pointerEvent.clientY, false);
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
  }

  const shown = drag ? orderProjects(sorted, moveId(sorted.map((project) => project.id), drag.id, drag.index)) : sorted;
  const dragging = drag ? projects.find((project) => project.id === drag.id) : undefined;

  return <section ref={desktop} className={`home-desktop ${drag ? "is-arranging" : ""}`} aria-labelledby="home-title">
    <h1 className="sr-only" id="home-title">Project desktop</h1>
    {projects.length ? <div className="project-folder-grid" ref={gridRef} style={{ ["--desktop-columns" as string]: columns }}>{shown.map((project) => {
      const selected = project.id === selectedProject;
      if (drag?.id === project.id) return <div className="folder-slot" key={project.id} aria-hidden="true" />;
      return <article className={`project-folder ${selected ? "selected" : ""}`} key={project.id}>
        <motion.button className="folder-card" layoutId={selected && !drag ? `project-shell-${project.id}` : undefined} aria-keyshortcuts="Alt+ArrowLeft Alt+ArrowRight Alt+ArrowUp Alt+ArrowDown" aria-roledescription="Draggable project folder" aria-pressed={selected} onClick={() => { if (suppressClick.current) { suppressClick.current = false; return; } setSelectedProject(project.id); }} onDoubleClick={() => { if (suppressClick.current) return; open(project.id); }} onKeyDown={(event) => { if (!event.altKey || !event.key.startsWith("Arrow")) return; event.preventDefault(); nudge(project.id, event.key); }} onPointerDown={(event) => beginDrag(event, project.id)} type="button">
          <FolderFace project={project} cover={coverAsset(assetById.get(project.id))} meta={metaFor(project)} tab={tabIndex(project.id)} />
        </motion.button>
        {selected ? <div className="folder-actions">
          <button onClick={() => open(project.id)} type="button"><FolderOpen size={14} /> Open</button>
          <button onClick={() => { setSelection({ type: "project", id: project.id }); setInspectorOpen(true); }} type="button"><Info size={14} /> Details</button>
        </div> : null}
      </article>;
    })}<button className="project-folder new-folder" onClick={onNewProject} type="button"><span className="folder-tab" /><span className="folder-body"><Plus size={18} /><strong>New project</strong><small>Start a creative space</small></span></button></div> : <div className="home-empty"><div className="home-empty-icon"><FolderOpen size={24} /></div><h2>Your desktop is empty</h2><p>Create a project to start building a world with Darius.</p><button className="primary-button" onClick={onNewProject} type="button"><Plus size={15} /> New project</button></div>}
    {drag && dragging ? <div className="folder-ghost" style={{ left: drag.x, top: drag.y }}><FolderFace project={dragging} cover={coverAsset(assetById.get(dragging.id))} meta={metaFor(dragging)} tab={tabIndex(dragging.id)} /></div> : null}
  </section>;
}
