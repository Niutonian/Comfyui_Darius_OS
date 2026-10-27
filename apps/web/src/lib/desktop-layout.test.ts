import { describe, expect, it } from "vitest";
import { desktopColumns, moveId, orderProjects, snapIndex } from "./desktop-layout";

describe("Desktop folder grid", () => {
  it("keeps a saved order and appends new projects", () => {
    const projects = [{ id: "c" }, { id: "a" }, { id: "b" }];
    expect(orderProjects(projects, ["b", "a"]).map((item) => item.id)).toEqual(["b", "a", "c"]);
  });

  it("moves a folder onto another grid slot", () => {
    expect(moveId(["a", "b", "c", "d"], "a", 2)).toEqual(["b", "c", "a", "d"]);
    expect(moveId(["a", "b"], "b", 0)).toEqual(["b", "a"]);
  });

  it("snaps a pointer to the nearest cell", () => {
    expect(snapIndex(10, 10, 4, 7, 190, 220, 54, 42)).toBe(0);
    expect(snapIndex(190 + 54 + 20, 12, 4, 7, 190, 220, 54, 42)).toBe(1);
    expect(snapIndex(20, 220 + 42 + 10, 4, 7, 190, 220, 54, 42)).toBe(4);
    expect(snapIndex(900, 900, 4, 7, 190, 220, 54, 42)).toBe(6);
  });

  it("fits as many columns as the desktop width allows", () => {
    expect(desktopColumns(800, 190, 54)).toBe(3);
    expect(desktopColumns(120, 190, 54)).toBe(1);
  });
});
