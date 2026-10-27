export type RegionKind = "group" | "object" | "character" | "text";
export type CanvasRegion = {
  id: string; parentId: string | null; name: string; kind: RegionKind;
  x: number; y: number; width: number; height: number; order: number;
  description: string; text: string; palette: string[]; visible: boolean; locked: boolean;
};
export type CanvasContent = {
  schemaVersion: 1; name: string; artboard: { preset: string; width: number; height: number };
  globalPrompt: string; regions: CanvasRegion[];
};
export type Rect = { x: number; y: number; width: number; height: number };
export type ResolvedRegion = { region: CanvasRegion; rect: Rect; depth: number; hidden: boolean; locked: boolean };
export type CanvasHistory = { past: CanvasContent[]; present: CanvasContent; future: CanvasContent[] };
export type CanvasViewport = { x: number; y: number; scale: number };
export const emptyCanvas = (): CanvasContent => ({ schemaVersion: 1, name: "Untitled canvas", artboard: { preset: "square", width: 1024, height: 1024 }, globalPrompt: "", regions: [] });
export const sameContent = (a: CanvasContent, b: CanvasContent) => JSON.stringify(a) === JSON.stringify(b);
export function commit(history: CanvasHistory, content: CanvasContent): CanvasHistory {
  return sameContent(history.present, content) ? history : { past: [...history.past, history.present].slice(-60), present: content, future: [] };
}
export function undo(history: CanvasHistory): CanvasHistory {
  return history.past.length ? { past: history.past.slice(0, -1), present: history.past.at(-1)!, future: [history.present, ...history.future] } : history;
}
export function redo(history: CanvasHistory): CanvasHistory {
  return history.future.length ? { past: [...history.past, history.present], present: history.future[0], future: history.future.slice(1) } : history;
}
export function resolveRegions(content: CanvasContent): ResolvedRegion[] {
  const result: ResolvedRegion[] = [], seen = new Set<string>();
  const visit = (parentId: string | null, parent: Rect, depth = 0, hidden = false, locked = false) => {
    if (depth > 12) throw new Error("Canvas hierarchy is too deep");
    content.regions.filter(r => r.parentId === parentId).sort((a, b) => a.order - b.order || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)).forEach(region => {
      if (seen.has(region.id)) throw new Error("Canvas hierarchy contains duplicate or cyclic IDs");
      seen.add(region.id);
      const rect = { x: parent.x + region.x * parent.width, y: parent.y + region.y * parent.height, width: region.width * parent.width, height: region.height * parent.height };
      result.push({ region, rect, depth, hidden: hidden || !region.visible, locked: locked || region.locked });
      visit(region.id, rect, depth + 1, hidden || !region.visible, locked || region.locked);
    });
  };
  visit(null, { x: 0, y: 0, ...content.artboard });
  if (seen.size !== content.regions.length) throw new Error("Canvas has a cycle or a missing parent");
  return result;
}
export function parentRect(content: CanvasContent, parentId: string | null): Rect {
  if (!parentId) return { x: 0, y: 0, width: content.artboard.width, height: content.artboard.height };
  const item = resolveRegions(content).find(r => r.region.id === parentId);
  if (!item) throw new Error("Parent region is missing");
  return item.rect;
}
export function normalizeDrag(a: { x: number; y: number }, b: { x: number; y: number }): Rect {
  return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(b.x - a.x), height: Math.abs(b.y - a.y) };
}
export function localRect(rect: Rect, parent: Rect): Rect {
  return { x: (rect.x - parent.x) / parent.width, y: (rect.y - parent.y) / parent.height, width: rect.width / parent.width, height: rect.height / parent.height };
}
export function clampRect(rect: Rect, parent: Rect): Rect {
  const width = Math.min(parent.width, Math.max(1, rect.width)), height = Math.min(parent.height, Math.max(1, rect.height));
  return { x: Math.max(parent.x, Math.min(parent.x + parent.width - width, rect.x)), y: Math.max(parent.y, Math.min(parent.y + parent.height - height, rect.y)), width, height };
}
export function updateRect(content: CanvasContent, id: string, rect: Rect): CanvasContent {
  const resolved = resolveRegions(content).find(item => item.region.id === id);
  if (!resolved || resolved.locked) return content;
  const parent = parentRect(content, resolved.region.parentId);
  const local = localRect(clampRect(rect, parent), parent);
  return { ...content, regions: content.regions.map(region => region.id === id ? { ...region, ...local } : region) };
}
export function descendants(content: CanvasContent, id: string): Set<string> {
  const ids = new Set([id]);
  for (let i = 0; i < content.regions.length; i++) content.regions.forEach(region => { if (region.parentId && ids.has(region.parentId)) ids.add(region.id); });
  return ids;
}
export function removeRegion(content: CanvasContent, id: string): CanvasContent {
  const ids = descendants(content, id);
  if (resolveRegions(content).some(item => ids.has(item.region.id) && item.locked)) throw new Error("Unlock this region and its descendants before deleting");
  return { ...content, regions: content.regions.filter(region => !ids.has(region.id)) };
}
export function reparentRegion(content: CanvasContent, id: string, parentId: string | null): CanvasContent {
  const resolved = resolveRegions(content), selected = resolved.find(item => item.region.id === id);
  if (!selected || selected.locked) return content;
  if (parentId && descendants(content, id).has(parentId)) throw new Error("A region cannot contain its own ancestor");
  if (resolved.find(item => item.region.id === parentId)?.locked) throw new Error("Unlock the new parent first");
  const parent = parentRect(content, parentId), local = localRect(selected.rect, parent);
  if (local.x < -1e-9 || local.y < -1e-9 || local.x + local.width > 1 + 1e-9 || local.y + local.height > 1 + 1e-9) throw new Error("The new parent must contain this region; resize or move it first");
  return { ...content, regions: content.regions.map(region => region.id === id ? { ...region, ...local, parentId, order: content.regions.length } : region) };
}
export function duplicateRegion(content: CanvasContent, id: string): { content: CanvasContent; selectedId: string } {
  const ids = descendants(content, id), mapping = new Map([...ids].map(key => [key, crypto.randomUUID()]));
  const root = content.regions.find(region => region.id === id);
  if (!root) throw new Error("Select a region first");
  if (content.regions.length + ids.size > 64) throw new Error("Canvas supports up to 64 regions");
  const copies = content.regions.filter(region => ids.has(region.id)).map(region => ({ ...region, id: mapping.get(region.id)!,
    parentId: mapping.get(region.parentId ?? "") ?? region.parentId, name: region.id === id ? `${region.name} copy` : region.name,
    locked: false, order: region.id === id ? content.regions.length : region.order }));
  return { content: { ...content, regions: [...content.regions, ...copies] }, selectedId: mapping.get(id)! };
}
export function reorderRegion(content: CanvasContent, id: string, direction: -1 | 1): CanvasContent {
  const selected = resolveRegions(content).find(r => r.region.id === id);
  if (!selected || selected.locked) return content;
  const siblings = content.regions.filter(r => r.parentId === selected.region.parentId).sort((a, b) => a.order - b.order || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const index = siblings.findIndex(r => r.id === id), other = index + direction;
  if (other < 0 || other >= siblings.length) return content;
  if (resolveRegions(content).find(r => r.region.id === siblings[other].id)?.locked) throw new Error("Unlock the adjacent layer before reordering");
  [siblings[index], siblings[other]] = [siblings[other], siblings[index]];
  const orders = new Map(siblings.map((r, order) => [r.id, order]));
  return { ...content, regions: content.regions.map(r => orders.has(r.id) ? { ...r, order: orders.get(r.id)! } : r) };
}
