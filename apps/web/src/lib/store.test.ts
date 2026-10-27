import { beforeEach, describe, expect, it } from "vitest";
import { useDariusStore } from "./store";

beforeEach(() => useDariusStore.setState({ selection: null, inspectorOpen: false, trayOpen: false, activeProjectId: "first", dariusMood: "idle" }));

describe("Contextual inspection", () => {
  it("opens details when an asset is selected, including after the inspector was closed", () => {
    useDariusStore.getState().setSelection({ type: "asset", id: "reference" });
    expect(useDariusStore.getState().inspectorOpen).toBe(true);
    useDariusStore.getState().setInspectorOpen(false);
    useDariusStore.getState().setSelection({ type: "character", id: "mara" });
    expect(useDariusStore.getState().inspectorOpen).toBe(true);
    expect(useDariusStore.getState().selection).toEqual({ type: "character", id: "mara" });
  });
  it("keeps the inspector and background job tray mutually exclusive", () => {
    useDariusStore.getState().setTrayOpen(true);
    expect(useDariusStore.getState()).toMatchObject({ trayOpen: true, inspectorOpen: false });

    useDariusStore.getState().setInspectorOpen(true);
    expect(useDariusStore.getState()).toMatchObject({ trayOpen: false, inspectorOpen: true });

    useDariusStore.getState().setTrayOpen(true);
    useDariusStore.getState().setSelection({ type: "job", id: "job-1" });
    expect(useDariusStore.getState()).toMatchObject({ trayOpen: false, inspectorOpen: true });
  });
  it("replaces the previous project's selection on a project switch", () => {
    useDariusStore.getState().setSelection({ type: "scene", id: "old-scene" });
    useDariusStore.getState().setActiveProject("second");
    expect(useDariusStore.getState().selection).toEqual({ type: "project", id: "second" });
  });
  it("tracks Darius mood without persisting it", () => {
    useDariusStore.getState().setDariusMood("thinking");
    expect(useDariusStore.getState().dariusMood).toBe("thinking");
    const persisted = JSON.parse(localStorage.getItem("darius-interface-v1")!).state;
    expect(persisted.dariusMood).toBeUndefined();
  });
});
