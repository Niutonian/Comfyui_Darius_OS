import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MOBILE_MEDIA, useMobileSheetFocus, useMobileShell } from "./use-mobile-shell";

afterEach(() => { vi.restoreAllMocks(); });

it("uses compact controls in short windows even with a mouse", () => {
  expect(MOBILE_MEDIA).toBe("(max-width: 760px), (max-width: 1000px) and (max-height: 500px)");
  const media = window.matchMedia(MOBILE_MEDIA);
  vi.spyOn(window, "matchMedia").mockImplementation(query => ({ ...media, matches: query === MOBILE_MEDIA }));
  const { result, unmount } = renderHook(() => useMobileShell(null, vi.fn()));
  expect(result.current).toBe(true);
  unmount();
});

it("follows the Android visual viewport, compacts chrome for the keyboard, and cleans up", async () => {
  const media = window.matchMedia("(max-width: 760px)");
  vi.spyOn(window, "matchMedia").mockReturnValue({ ...media, matches: true });
  const original = Object.getOwnPropertyDescriptor(window, "visualViewport");
  const viewport = Object.assign(new EventTarget(), { height: 844, offsetTop: 0 });
  Object.defineProperty(window, "visualViewport", { configurable: true, value: viewport });
  const input = document.createElement("textarea");
  document.body.appendChild(input);
  const dismiss = vi.fn();
  const hook = renderHook(() => useMobileShell(null, dismiss));
  try {
    await waitFor(() => expect(document.documentElement.style.getPropertyValue("--darius-viewport-height")).toBe("844px"));
    act(() => { input.focus(); viewport.height = 500; viewport.dispatchEvent(new Event("resize")); });
    await waitFor(() => expect(document.documentElement.dataset.mobileKeyboard).toBe("true"));
    expect(document.documentElement.style.getPropertyValue("--darius-viewport-height")).toBe("500px");
    act(() => { input.blur(); viewport.height = 844; viewport.dispatchEvent(new Event("resize")); });
    await waitFor(() => expect(document.documentElement.dataset.mobileKeyboard).toBe("false"));
    hook.unmount();
    expect(document.documentElement.style.getPropertyValue("--darius-viewport-height")).toBe("");
  } finally {
    hook.unmount(); input.remove();
    if (original) Object.defineProperty(window, "visualViewport", original);
    else Reflect.deleteProperty(window, "visualViewport");
  }
});

it("does not apply phone viewport styles to the desktop", () => {
  const { result, unmount } = renderHook(() => useMobileShell(null, vi.fn()));
  expect(result.current).toBe(false);
  expect(document.documentElement.style.getPropertyValue("--darius-viewport-height")).toBe("");
  unmount();
});

it("focuses the sheet close action, traps keyboard focus, and supports Escape", async () => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{ width: 44, height: 44 }] as unknown as DOMRectList);
  const close = vi.fn();
  function Sheet() {
    useMobileSheetFocus(".test-sheet", close);
    return <section className="test-sheet"><button aria-label="Close test sheet">Close</button><input aria-label="Last sheet input" /></section>;
  }
  render(<Sheet />);
  const first = screen.getByRole("button", { name: "Close test sheet" }), last = screen.getByRole("textbox");
  await waitFor(() => expect(first).toHaveFocus());
  last.focus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(first).toHaveFocus();
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
  expect(last).toHaveFocus();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(close).toHaveBeenCalledTimes(1);
});
