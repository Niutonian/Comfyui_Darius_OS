import { describe, expect, it } from "vitest";
import { arrangeNodes, buildStoryMap, canDive, focusStoryMap } from "./story-map";
import type { Asset, Character, Project, Scene, Workflow } from "./types";

const project = { id: "film", name: "Film" } as Project;
const assets = Array.from({ length: 8 }, (_, i) => ({ id: `asset-${i}`, kind: "image", role: "reference", metadata: {}, parent_asset_ids: [], provider: "local", approval_state: "approved" } as unknown as Asset));

describe("Story map relationships", () => {
  it("keeps media beyond the old six-item limit and connects approved references and scenes", () => {
    const character = { id: "mara", name: "Mara", approved_reference_asset_ids: ["asset-7"] } as Character;
    const scene = { id: "forest", title: "Forest", number: 1, status: "draft" } as Scene;
    const media = assets.map((asset, i) => ({ ...asset, scene_id: i === 7 ? "forest" : null }));
    const graph = buildStoryMap(project, [character], [scene], media, []);
    expect(graph.nodes.filter((node) => node.data.kind === "asset")).toHaveLength(8);
    expect(graph.edges).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: "character:mara", target: "asset:asset-7", label: "Approved reference" }),
      expect.objectContaining({ source: "scene:forest", target: "asset:asset-7", label: "Scene media" }),
    ]));
    const ids = new Set(graph.nodes.map((node) => node.id));
    expect(graph.edges.every((edge) => ids.has(edge.source) && ids.has(edge.target))).toBe(true);
  });
  it("shows actual media lineage without dangling parent links", () => {
    const graph = buildStoryMap(project, [], [], [assets[0], { ...assets[1], parent_asset_ids: ["asset-0", "unavailable"] }], []);
    expect(graph.edges.filter((edge) => edge.label === "Derived from")).toEqual([expect.objectContaining({ source: "asset:asset-0", target: "asset:asset-1" })]);
  });
  it("keeps World focused on the story while workflows remain available in Tools", () => {
    const character = { id: "mara", name: "Mara", approved_reference_asset_ids: ["asset-0"] } as Character;
    const scene = { id: "forest", title: "Forest", number: 1, status: "draft" } as Scene;
    const workflow = { id: "video", name: "Video", capability: "image-to-video", output: { kind: "video" }, execution_provider: "local-comfyui" } as Workflow;
    const graph = buildStoryMap(project, [character], [scene], assets, [workflow]);
    const world = focusStoryMap(graph, "world", null);
    expect(world.nodes.map((node) => node.data.kind).sort()).toEqual(["character", "project", "scene"]);
    expect(world.nodes.some((node) => node.data.kind === "asset")).toBe(false);
    expect(focusStoryMap(graph, "tools", null).nodes.map((node) => node.data.kind).sort()).toEqual(["project", "workflow"]);
  });
  it("arranges the visible cards into separated columns", () => {
    const graph = buildStoryMap(project, [{ id: "mara", name: "Mara", approved_reference_asset_ids: [] } as unknown as Character], [{ id: "forest", title: "Forest", number: 1, status: "draft" } as Scene], assets.slice(0, 2), []);
    const placed = arrangeNodes(graph.nodes);
    expect(placed["project:film"].x).toBeLessThan(placed["character:mara"].x);
    expect(placed["character:mara"].x).toBeLessThan(placed["scene:forest"].x);
    expect(placed["scene:forest"].x).toBeLessThan(placed["asset:asset-0"].x);
    expect(placed["asset:asset-0"].y).not.toBe(placed["asset:asset-1"].y);
  });
  it("dives into a character territory with connected references", () => {
    const character = { id: "mara", name: "Mara", approved_reference_asset_ids: ["asset-0"] } as Character;
    const graph = buildStoryMap(project, [character], [], [assets[0], assets[1]], []);
    const territory = focusStoryMap(graph, "world", { kind: "character", entityId: "mara" });
    expect(territory.focusId).toBe("character:mara");
    expect(territory.nodes.map((node) => node.id).sort()).toEqual(["asset:asset-0", "character:mara", "project:film"]);
    expect(canDive("character")).toBe(true);
    expect(canDive("workflow")).toBe(false);
  });
  it("keeps only character-linked media on the cast level", () => {
    const character = { id: "mara", name: "Mara", approved_reference_asset_ids: ["asset-0"] } as Character;
    const graph = buildStoryMap(project, [character], [], [assets[0], assets[1]], []);
    const cast = focusStoryMap(graph, "cast", null);
    expect(cast.nodes.filter((node) => node.data.kind === "asset").map((node) => node.id)).toEqual(["asset:asset-0"]);
  });
});
