import { expect, it } from "vitest";
import { alignPlacements, boardsInFrame, distributePlacements, frameAround, lineageEdges } from "./canvas-arrange";
import type { MossBoard, Placement } from "./moss-workspace";

const at = (boardId: string, x: number, y: number, w = 300, h = 400): Placement => ({ boardId, x, y, displayWidth: w, displayHeight: h, order: 0 });

it("aligns edges and centres", () => {
  const items = [at("a", 100, 40), at("b", 20, 300, 200), at("c", 400, 10)];
  expect(alignPlacements(items, "left").map(p => p.x)).toEqual([20, 20, 20]);
  expect(alignPlacements(items, "top").map(p => p.y)).toEqual([10, 10, 10]);
  const centred = alignPlacements(items, "centre-x");
  expect(new Set(centred.map(p => p.x + p.displayWidth / 2)).size).toBe(1);
});

it("distributes with equal gaps and keeps the outer boards in place", () => {
  const spread = distributePlacements([at("a", 0, 0, 100), at("c", 1000, 0, 100), at("b", 150, 0, 300)], "x");
  const byId = Object.fromEntries(spread.map(p => [p.boardId, p.x]));
  expect(byId.a).toBe(0); expect(byId.c).toBe(1000);
  expect(byId.b - (byId.a + 100)).toBeCloseTo(byId.c - (byId.b + 300));
});

it("frames a selection with padding and finds the boards a frame holds", () => {
  const frame = frameAround([at("a", 0, 0), at("b", 500, 100)], 40);
  expect(frame).toEqual({ x: -40, y: -68, width: 880, height: 608 });
  expect(boardsInFrame(frame, [at("a", 0, 0), at("b", 500, 100), at("far", 5000, 0)])).toEqual(["a", "b"]);
});

it("draws lineage from a result to the boards that pin or use it", () => {
  const board = (id: string, patch: Partial<MossBoard>) => ({ id, settings: { references: [] }, recentAssetIds: [], activeResult: null, ...patch }) as unknown as MossBoard;
  const edges = lineageEdges([
    board("gate", { recentAssetIds: ["img-1"] }),
    board("portrait", { settings: { references: [{ sourceBoardId: "gate" }] } as never }),
    board("edit", { settings: { references: [], image: { activeProfile: "qwen21-edit-v1", drafts: { "qwen21-edit-v1": { inputs: [{ assetId: "img-1" }] } } } } as never }),
    board("video", { settings: { references: [], video: { activeMode: "animate-image", modeDrafts: { "animate-image": { inputs: [{ assetId: "img-1" }, { assetId: "unknown" }] } } } } as never }),
  ]);
  expect(edges).toEqual([
    { from: "gate", to: "portrait", kind: "reference" },
    { from: "gate", to: "edit", kind: "input" },
    { from: "gate", to: "video", kind: "input" },
  ]);
});
