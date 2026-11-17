import { afterEach, expect, it, vi } from "vitest";
import { findBoard, parseCommand, registerDesktopActions, tryDesktopCommand } from "./desktop-commands";

const boards = [{ id: "b1", name: "Forest gate" }, { id: "b2", name: "Mara portrait" }, { id: "b3", name: "Forest lantern" }];
const parse = (text: string, selected: string | null = null) => parseCommand(text, boards, selected);
let undo: (() => void) | null = null;
afterEach(() => { undo?.(); undo = null; });

it("opens and closes apps from natural phrasings", () => {
  expect(parse("Open the library")).toEqual({ kind: "open-app", app: "library" });
  expect(parse("Darius, show me my ideas please.")).toEqual({ kind: "open-app", app: "ideas" });
  expect(parse("go to the timeline")).toEqual({ kind: "open-app", app: "edit" });
  expect(parse("close the world map")).toEqual({ kind: "close-app", app: "map" });
  expect(parse("back to the canvas")).toEqual({ kind: "show-canvas" });
});

it("finds boards by name, or uses the selected board for this/it", () => {
  expect(parse("generate the forest gate board")).toEqual({ kind: "generate-board", boardId: "b1" });
  expect(parse("open mara")).toEqual({ kind: "open-board", boardId: "b2" });
  expect(parse("render this", "b3")).toEqual({ kind: "generate-board", boardId: "b3" });
  expect(parse("compare the last two versions", "b2")).toEqual({ kind: "compare-board", boardId: "b2" });
  expect(parse("compare versions of forest gate")).toEqual({ kind: "compare-board", boardId: "b1" });
  expect(findBoard("forest", boards, null)).toBeNull(); // ambiguous: two forest boards
});

it("leaves ordinary conversation alone", () => {
  for (const text of ["What should the forest gate look like at dawn?", "generate", "open", "show me something moody for the gate", "I want to open a new scene with Mara walking"])
    expect(parse(text)).toBeNull();
  expect(parse("generate", "b1")).toEqual({ kind: "generate-board", boardId: "b1" });
});

it("adds boards, notes and frames", () => {
  expect(parse("new FIBO board")).toEqual({ kind: "new-board", board: "fibo" });
  expect(parse("add a sticky note")).toEqual({ kind: "new-board", board: "note" });
  expect(parse("create a frame")).toEqual({ kind: "new-board", board: "frame" });
});

it("runs through whatever parts of the desktop registered, and declines when none can", () => {
  expect(tryDesktopCommand("open the library")).toBeNull();
  const openApp = vi.fn(), generateBoard = vi.fn();
  undo = registerDesktopActions({ openApp, generateBoard, boards: () => boards, selectedBoard: () => "b2" });
  expect(tryDesktopCommand("open the library")).toBe("Opened Library.");
  expect(openApp).toHaveBeenCalledWith("library");
  expect(tryDesktopCommand("generate this")).toBe("Generating Mara portrait.");
  expect(generateBoard).toHaveBeenCalledWith("b2");
  expect(tryDesktopCommand("tell me a story")).toBeNull();
});
