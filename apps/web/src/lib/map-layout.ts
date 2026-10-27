"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

type Point = { x: number; y: number };
type LayoutState = {
  projects: Record<string, Record<string, Point>>;
  moveNode: (projectId: string, nodeId: string, point: Point) => void;
  placeNodes: (projectId: string, positions: Record<string, Point>) => void;
};

// Personal arrangement is local to this browser; creative relationships stay in the API.
export const useMapLayout = create<LayoutState>()(persist((set) => ({
  projects: {},
  moveNode: (projectId, nodeId, point) => {
    if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) return;
    set((state) => ({ projects: { ...state.projects, [projectId]: { ...state.projects[projectId], [nodeId]: { x: point.x, y: point.y } } } }));
  },
  placeNodes: (projectId, positions) => {
    const valid = Object.fromEntries(Object.entries(positions).filter(([, point]) => Number.isFinite(point.x) && Number.isFinite(point.y)));
    set((state) => ({ projects: { ...state.projects, [projectId]: { ...state.projects[projectId], ...valid } } }));
  },
}), { name: "darius-map-layout-v1", partialize: (state) => ({ projects: state.projects }) }));
