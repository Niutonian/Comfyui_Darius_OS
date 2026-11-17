import type { Annotation, MossBoard, Placement } from "./moss-workspace";

/** Pure layout helpers for several selected boards, frames, and lineage edges. */

export function alignPlacements(placements: Placement[], edge: "left" | "top" | "centre-x" | "centre-y"): Placement[] {
  if (placements.length < 2) return placements;
  if (edge === "left") { const x = Math.min(...placements.map(p => p.x)); return placements.map(p => ({ ...p, x })); }
  if (edge === "top") { const y = Math.min(...placements.map(p => p.y)); return placements.map(p => ({ ...p, y })); }
  if (edge === "centre-x") { const c = average(placements.map(p => p.x + p.displayWidth / 2)); return placements.map(p => ({ ...p, x: c - p.displayWidth / 2 })); }
  const c = average(placements.map(p => p.y + p.displayHeight / 2));
  return placements.map(p => ({ ...p, y: c - p.displayHeight / 2 }));
}

/** Even gaps between boards along one axis, keeping the first and last where they are. */
export function distributePlacements(placements: Placement[], axis: "x" | "y"): Placement[] {
  if (placements.length < 3) return placements;
  const size = axis === "x" ? "displayWidth" : "displayHeight";
  const sorted = [...placements].sort((a, b) => a[axis] - b[axis]);
  const first = sorted[0], last = sorted[sorted.length - 1];
  const span = last[axis] + last[size] - first[axis], used = sorted.reduce((sum, p) => sum + p[size], 0);
  const gap = (span - used) / (sorted.length - 1);
  let cursor = first[axis];
  const placed = new Map(sorted.map(p => { const next = { ...p, [axis]: cursor }; cursor += p[size] + gap; return [p.boardId, next]; }));
  return placements.map(p => placed.get(p.boardId)!);
}

/** A frame just big enough to hold the given boards, with room for its title. */
export function frameAround(placements: Placement[], padding = 48): Pick<Annotation, "x" | "y" | "width" | "height"> {
  const left = Math.min(...placements.map(p => p.x)) - padding, top = Math.min(...placements.map(p => p.y)) - padding - 28;
  const right = Math.max(...placements.map(p => p.x + p.displayWidth)) + padding, bottom = Math.max(...placements.map(p => p.y + p.displayHeight)) + padding;
  return { x: left, y: top, width: right - left, height: bottom - top };
}

/** Boards whose centre sits inside a frame move with it. */
export function boardsInFrame(frame: Pick<Annotation, "x" | "y" | "width" | "height">, placements: Placement[]) {
  return placements.filter(p => { const cx = p.x + p.displayWidth / 2, cy = p.y + p.displayHeight / 2; return cx >= frame.x && cx <= frame.x + frame.width && cy >= frame.y && cy <= frame.y + frame.height; }).map(p => p.boardId);
}

export function intersects(a: { x: number; y: number; width: number; height: number }, p: Placement) {
  return p.x < a.x + a.width && p.x + p.displayWidth > a.x && p.y < a.y + a.height && p.y + p.displayHeight > a.y;
}

export type LineageEdge = { from: string; to: string; kind: "input" | "reference" };

/**
 * Where things came from: a board feeds another when one of its results is pinned as a
 * visual note, or used as an image or video input there.
 */
export function lineageEdges(boards: MossBoard[]): LineageEdge[] {
  const producer = new Map<string, string>();
  for (const board of boards) for (const id of [...(board.recentAssetIds ?? []), ...(board.activeResult?.assetIds ?? [])]) if (!producer.has(id)) producer.set(id, board.id);
  const edges: LineageEdge[] = [], seen = new Set<string>();
  const push = (edge: LineageEdge) => { const key = `${edge.from}>${edge.to}:${edge.kind}`; if (edge.from !== edge.to && !seen.has(key)) { seen.add(key); edges.push(edge); } };
  for (const board of boards) {
    for (const ref of board.settings.references ?? []) push({ from: ref.sourceBoardId, to: board.id, kind: "reference" });
    const image = board.settings.image, video = board.settings.video;
    const inputs = [...(image ? image.drafts[image.activeProfile]?.inputs ?? [] : []), ...(video ? video.modeDrafts[video.activeMode]?.inputs ?? [] : [])];
    for (const input of inputs) { const from = producer.get(input.assetId); if (from) push({ from, to: board.id, kind: "input" }); }
  }
  return edges;
}

function average(values: number[]) { return values.reduce((sum, v) => sum + v, 0) / values.length; }
