import { beforeEach, expect, it } from "vitest";
import { appForView } from "./desktop-apps";
import { DESKTOP_INSET, MIN_WINDOW, clampWindow, focusedWindow, useWindowStore } from "./window-store";

const viewport = { width: 1440, height: 900 };
const store = () => useWindowStore.getState();
const windows = (scope = "p") => store().scopes[scope] ?? [];
beforeEach(() => useWindowStore.setState({ scopes: {} }));

it("opens one window per app and raises an existing one instead of duplicating it", () => {
  store().open("p", "library", viewport);
  store().open("p", "chat", viewport);
  store().open("p", "library", viewport);
  expect(windows().map(w => w.app).sort()).toEqual(["chat", "library"]);
  expect(focusedWindow(windows())?.app).toBe("library");
});

it("keeps z-order small and ordered across many focus changes", () => {
  store().open("p", "library", viewport); store().open("p", "chat", viewport); store().open("p", "map", viewport);
  for (let i = 0; i < 50; i++) store().focus("p", i % 2 ? "library" : "chat");
  expect(windows().map(w => w.z).sort()).toEqual([1, 2, 3]);
  expect(focusedWindow(windows())?.app).toBe("library");
});

it("minimized windows are never focused and reopen in their previous mode", () => {
  store().open("p", "edit", viewport);
  expect(windows()[0].mode).toBe("maximized");
  store().open("p", "chat", viewport);
  store().minimize("p", "chat");
  expect(focusedWindow(windows())?.app).toBe("edit");
  store().open("p", "chat", viewport);
  expect(windows().find(w => w.app === "chat")?.mode).toBe("normal");
  store().minimizeAll("p");
  expect(focusedWindow(windows())).toBeNull();
});

it("keeps windows per project and closes only within a project", () => {
  store().open("a", "library", viewport); store().open("b", "map", viewport);
  store().close("a", "library");
  expect(windows("a")).toEqual([]);
  expect(windows("b").map(w => w.app)).toEqual(["map"]);
});

it("clamps size to the free area and keeps the title bar reachable", () => {
  expect(clampWindow({ x: -5000, y: -40, w: 99999, h: 10 }, viewport)).toEqual({
    x: DESKTOP_INSET.left - (viewport.width - DESKTOP_INSET.left - DESKTOP_INSET.right) + 96,
    y: DESKTOP_INSET.top, w: viewport.width - DESKTOP_INSET.left - DESKTOP_INSET.right, h: MIN_WINDOW.h,
  });
  const placed = clampWindow({ x: 5000, y: 5000, w: 600, h: 400 }, viewport);
  expect(placed.x).toBeLessThan(viewport.width);
  expect(placed.y).toBeLessThan(viewport.height - 40);
});

it("maps URL views to windows; create and home are the canvas and the launcher", () => {
  expect(appForView("talk")).toBe("chat");
  expect(appForView("edit")).toBe("edit");
  expect(appForView("create")).toBeNull();
  expect(appForView("home")).toBeNull();
});
