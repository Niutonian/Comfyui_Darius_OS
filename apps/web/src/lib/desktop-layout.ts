"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

type DesktopState = {
  order: string[];
  setOrder: (order: string[]) => void;
};

export const useDesktopOrder = create<DesktopState>()(persist((set) => ({
  order: [],
  setOrder: (order) => set({ order }),
}), { name: "darius-desktop-order-v1" }));

export function orderProjects<T extends { id: string }>(projects: T[], order: string[]) {
  const rank = new Map(order.map((id, index) => [id, index]));
  return projects.map((project, index) => ({ project, index }))
    .sort((left, right) => (rank.get(left.project.id) ?? Number.MAX_SAFE_INTEGER) - (rank.get(right.project.id) ?? Number.MAX_SAFE_INTEGER) || left.index - right.index)
    .map((item) => item.project);
}

export function moveId(ids: string[], id: string, index: number) {
  const from = ids.indexOf(id);
  if (from < 0) return ids;
  const next = ids.filter((item) => item !== id);
  const target = Math.max(0, Math.min(index, next.length));
  next.splice(target, 0, id);
  return next;
}

export function snapIndex(localX: number, localY: number, columns: number, count: number, cellW: number, cellH: number, gapX: number, gapY: number) {
  if (count <= 1 || columns < 1) return 0;
  const col = Math.max(0, Math.min(columns - 1, Math.round(localX / (cellW + gapX))));
  const maxRow = Math.max(0, Math.ceil(count / columns) - 1);
  const row = Math.max(0, Math.min(maxRow, Math.round(localY / (cellH + gapY))));
  return Math.max(0, Math.min(count - 1, row * columns + col));
}

export function desktopColumns(width: number, cell: number, gap: number) {
  if (cell <= 0) return 1;
  return Math.max(1, Math.floor((width + gap) / (cell + gap)));
}
