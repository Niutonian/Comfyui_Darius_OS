import { beforeEach, describe, expect, it } from "vitest";
import { useMapLayout } from "./map-layout";

beforeEach(() => useMapLayout.setState({ projects: {} }));
describe("Personal map arrangement", () => {
  it("moves only the chosen node and keeps projects separate", () => {
    const { moveNode } = useMapLayout.getState();
    moveNode("film-a", "asset:one", { x: 20, y: 30 });
    moveNode("film-a", "asset:two", { x: 100, y: 200 });
    moveNode("film-b", "asset:one", { x: 5, y: 8 });
    moveNode("film-a", "asset:one", { x: 40, y: 60 });
    expect(useMapLayout.getState().projects).toEqual({
      "film-a": { "asset:one": { x: 40, y: 60 }, "asset:two": { x: 100, y: 200 } },
      "film-b": { "asset:one": { x: 5, y: 8 } },
    });
    expect(JSON.parse(localStorage.getItem("darius-map-layout-v1")!).state.projects).toEqual(useMapLayout.getState().projects);
  });
  it("places many cards without dropping existing ones", () => {
    useMapLayout.getState().moveNode("film", "kept", { x: 1, y: 2 });
    useMapLayout.getState().placeNodes("film", { "asset:a": { x: 10, y: 20 }, "asset:b": { x: 30, y: 40 }, bad: { x: Number.NaN, y: 1 } });
    expect(useMapLayout.getState().projects.film).toEqual({ kept: { x: 1, y: 2 }, "asset:a": { x: 10, y: 20 }, "asset:b": { x: 30, y: 40 } });
  });
  it("does not persist invalid coordinates", () => {
    useMapLayout.getState().moveNode("film", "node", { x: NaN, y: Infinity });
    expect(useMapLayout.getState().projects).toEqual({});
  });
});
