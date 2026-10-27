import { expect, it } from "vitest";
import { clampRect, commit, duplicateRegion, emptyCanvas, normalizeDrag, redo, removeRegion, reparentRegion, resolveRegions, undo, updateRect, type CanvasContent, type CanvasRegion } from "./canvas-document";
const region = (id: string, values: Partial<CanvasRegion> = {}): CanvasRegion => ({ id, parentId: null, name: id, kind: "object", x: .25, y: .25, width: .5, height: .5, order: 0, description: "A cube", text: "", palette: [], visible: true, locked: false, ...values });
function document(): CanvasContent { return { ...emptyCanvas(), artboard: { preset: "photo", width: 1536, height: 1024 }, regions: [region("parent", { kind: "group" }), region("child", { parentId: "parent", x: .5, y: 0, width: .5, height: .5 })] }; }
it("resolves the handoff nested example without viewport or DPR state", () => {
  const content = document(), original = structuredClone(content);
  expect(resolveRegions(content)[1].rect).toEqual({ x: 768, y: 256, width: 384, height: 256 });
  expect(content).toEqual(original);
});
it("normalizes reverse drags and clamps within parent bounds", () => {
  expect(normalizeDrag({ x: 90, y: 80 }, { x: 20, y: 30 })).toEqual({ x: 20, y: 30, width: 70, height: 50 });
  expect(clampRect({ x: -50, y: 1000, width: 50, height: 20 }, { x: 20, y: 30, width: 200, height: 100 })).toEqual({ x: 20, y: 110, width: 50, height: 20 });
});
it("moves and scales descendants through relative geometry", () => {
  const content = document();
  const next = updateRect(content, "parent", { x: 0, y: 0, width: 1536, height: 1024 });
  expect(resolveRegions(next)[1].rect).toEqual({ x: 768, y: 0, width: 768, height: 512 });
  expect(next.regions[1]).toEqual(content.regions[1]);
});
it("reparents without changing absolute geometry and rejects cycles", () => {
  const content = document(), old = resolveRegions(content)[1].rect;
  const root = reparentRegion(content, "child", null);
  expect(resolveRegions(root).find(r => r.region.id === "child")?.rect).toEqual(old);
  expect(() => reparentRegion(content, "parent", "child")).toThrow("ancestor");
});
it("honours inherited visibility and document locks", () => {
  const content = document(); content.regions[0].visible = false; content.regions[0].locked = true;
  expect(resolveRegions(content).every(value => value.hidden && value.locked)).toBe(true);
  expect(updateRect(content, "child", { x: 0, y: 0, width: 50, height: 50 })).toBe(content);
  expect(() => removeRegion(content, "parent")).toThrow("Unlock");
});
it("duplicates an entire subtree with fresh stable identities", () => {
  const content = document(), copy = duplicateRegion(content, "parent");
  expect(copy.content.regions).toHaveLength(4);
  expect(copy.selectedId).not.toBe("parent");
  expect(copy.content.regions[3].parentId).toBe(copy.selectedId);
  expect(resolveRegions(copy.content)[3].rect).toEqual(resolveRegions(content)[1].rect);
});
it("deletes descendants but not siblings", () => {
  const content = document(); content.regions.push(region("sibling"));
  expect(removeRegion(content, "parent").regions.map(r => r.id)).toEqual(["sibling"]);
});
it("commits one gesture, restores exact snapshots, and clears redo after a new edit", () => {
  const original = document(), next = updateRect(original, "parent", { x: 0, y: 0, width: 500, height: 500 });
  const edited = commit({ present: original, past: [], future: [] }, next);
  expect(edited.past).toHaveLength(1);
  expect(undo(edited).present).toEqual(original);
  expect(redo(undo(edited)).present).toEqual(next);
  expect(commit(undo(edited), { ...original, globalPrompt: "New direction" }).future).toEqual([]);
});
it("uses the same ASCII tie-break order as the server", () => {
  const content = emptyCanvas(); content.regions = [region("b"), region("a"), region("A")];
  expect(resolveRegions(content).map(r => r.region.id)).toEqual(["A", "a", "b"]);
});
