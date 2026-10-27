"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { DariusMood, Job, Project, Selection, ThemeMode, ViewId } from "./types";
import { readWorkspaceValue, rememberWorkspaceValue } from "./workspace-session";

function projectContext(state: DariusState, id: string | null) {
  if (id === state.activeProjectId) return { referenceAssetIds: state.referenceAssetIds, selection: state.selection };
  if (state.activeProjectId) rememberWorkspaceValue(`project-context:${state.activeProjectId}`, { referenceAssetIds: state.referenceAssetIds, selection: state.selection });
  return (id ? readWorkspaceValue<{ referenceAssetIds: string[]; selection: Selection }>(`project-context:${id}`) : undefined)
    ?? { referenceAssetIds: [], selection: id ? { type: "project" as const, id } : null };
}

type DariusState = {
  view: ViewId;
  theme: ThemeMode;
  dariusMood: DariusMood;
  projects: Project[];
  activeProjectId: string | null;
  knownJobIds: string[];
  referenceAssetIds: string[];
  addReferenceAsset: (assetId: string) => void;
  removeReferenceAsset: (assetId: string) => void;
  selection: Selection;
  inspectorOpen: boolean;
  trayOpen: boolean;
  lastView: ViewId;
  setView: (view: ViewId) => void;
  openProject: (id: string) => void;
  setTheme: (theme: ThemeMode) => void;
  setDariusMood: (mood: DariusMood) => void;
  setProjects: (projects: Project[]) => void;
  addProject: (project: Project) => void;
  setActiveProject: (id: string | null) => void;
  rememberJob: (job: Job) => void;
  setSelection: (selection: Selection) => void;
  setInspectorOpen: (open: boolean) => void;
  setTrayOpen: (open: boolean) => void;
};

export const useDariusStore = create<DariusState>()(
  persist(
    (set) => ({
      view: "home",
      theme: "light",
      dariusMood: "idle",
      projects: [],
      activeProjectId: null,
      knownJobIds: [],
      referenceAssetIds: [],
      addReferenceAsset: (assetId) => set((state) => ({ referenceAssetIds: [...new Set([...state.referenceAssetIds, assetId])].slice(0, 4) })),
      removeReferenceAsset: (assetId) => set((state) => ({ referenceAssetIds: state.referenceAssetIds.filter((id) => id !== assetId) })),
      selection: null,
      inspectorOpen: false,
      trayOpen: false,
      lastView: "talk",
      setView: (view) => set((state) => ({ view, lastView: view === "home" || view === "settings" ? state.lastView : view })),
      openProject: (id) => set((state) => ({
        activeProjectId: id,
        ...projectContext(state, id),
        view: state.lastView === "home" || state.lastView === "settings" ? "talk" : state.lastView,
        lastView: state.lastView === "home" || state.lastView === "settings" ? "talk" : state.lastView,
      })),
      setTheme: (theme) => set({ theme }),
      setDariusMood: (dariusMood) => set({ dariusMood }),
      setProjects: (projects) =>
        set((state) => {
          const activeProjectId = projects.some((project) => project.id === state.activeProjectId)
            ? state.activeProjectId
            : (projects[0]?.id ?? null);
          return { projects, activeProjectId, ...projectContext(state, activeProjectId) };
        }),
      addProject: (project) =>
        set((state) => ({
          projects: [...state.projects.filter((item) => item.id !== project.id), project],
          activeProjectId: project.id,
          ...projectContext(state, project.id),
        })),
      setActiveProject: (activeProjectId) =>
        set((state) => ({ activeProjectId, ...projectContext(state, activeProjectId) })),
      rememberJob: (job) =>
        set((state) => ({
          knownJobIds: state.knownJobIds.includes(job.id)
            ? state.knownJobIds
            : [job.id, ...state.knownJobIds].slice(0, 50),
          selection: { type: "job", id: job.id },
          trayOpen: true,
          inspectorOpen: false,
        })),
      setSelection: (selection) => set({ selection, inspectorOpen: Boolean(selection), trayOpen: false }),
      setInspectorOpen: (inspectorOpen) => set({ inspectorOpen, ...(inspectorOpen ? { trayOpen: false } : {}) }),
      setTrayOpen: (trayOpen) => set({ trayOpen, ...(trayOpen ? { inspectorOpen: false } : {}) }),
    }),
    {
      name: "darius-interface-v1",
      partialize: (state) => ({
        view: state.view,
        theme: state.theme,
        projects: state.projects,
        activeProjectId: state.activeProjectId,
        knownJobIds: state.knownJobIds,
        inspectorOpen: state.inspectorOpen,
        trayOpen: state.trayOpen,
        lastView: state.lastView,
      }),
    },
  ),
);
