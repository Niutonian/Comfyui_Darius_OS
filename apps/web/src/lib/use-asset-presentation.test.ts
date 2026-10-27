import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api-client";
import type { Asset, Message } from "./types";
import { useAssetPresentation } from "./use-asset-presentation";

const asset = (id: string, project_id = "p") => ({ id, project_id, kind: "image", metadata: { display_name: id } } as unknown as Asset);
const message = (id: string, action = "open", ids: string[] = ["a"], project_id = "p") => ({ id, conversation_id: "chat", role: "assistant", metadata: { presentation_actions: [{ action, asset_ids: action === "open" ? ids : [], project_id }] } } as unknown as Message);
afterEach(() => vi.restoreAllMocks());

it("opens only a new scoped receipt and does not replay it after closing", async () => {
  const get = vi.spyOn(api, "asset").mockResolvedValue(asset("a"));
  const { result } = renderHook(() => useAssetPresentation("p", "chat", true));
  await act(async () => result.current.present(message("reply")));
  expect(result.current.gallery?.assets[0].id).toBe("a");
  act(() => result.current.close());
  await act(async () => result.current.present(message("reply")));
  expect(result.current.gallery).toBeNull(); expect(get).toHaveBeenCalledOnce();
});
it("navigates a gallery and closes without fetching or running anything again", async () => {
  const get = vi.spyOn(api, "asset").mockImplementation(async (id) => asset(id));
  const { result } = renderHook(() => useAssetPresentation("p", "chat", true));
  await act(async () => result.current.present(message("open", "open", ["a", "b"])));
  await act(async () => result.current.present(message("next", "next")));
  expect(result.current.gallery?.index).toBe(1);
  await act(async () => result.current.present(message("previous", "previous")));
  expect(result.current.gallery?.index).toBe(0);
  await act(async () => result.current.present(message("close", "close")));
  expect(result.current.gallery).toBeNull(); expect(get).toHaveBeenCalledTimes(2);
});
it("rejects foreign receipts before loading media", async () => {
  const get = vi.spyOn(api, "asset");
  const { result } = renderHook(() => useAssetPresentation("p", "chat", true));
  await act(async () => result.current.present(message("foreign", "open", ["secret"], "other")));
  expect(result.current.gallery).toBeNull(); expect(get).not.toHaveBeenCalled();
});
it("rejects foreign metadata even when an API response is mis-scoped", async () => {
  vi.spyOn(api, "asset").mockResolvedValue(asset("a", "other"));
  const { result } = renderHook(() => useAssetPresentation("p", "chat", true));
  await act(async () => result.current.present(message("reply")));
  expect(result.current.gallery).toBeNull(); expect(result.current.error).toContain("project");
});
it("does not open a late response after a thread switch or a manual close", async () => {
  let finish!: (value: Asset) => void;
  vi.spyOn(api, "asset").mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  const { result, rerender } = renderHook(({ chat }) => useAssetPresentation("p", chat, true), { initialProps: { chat: "chat" } });
  let pending!: Promise<void>;
  act(() => { pending = result.current.present(message("reply")); });
  rerender({ chat: "different" });
  await act(async () => { finish(asset("a")); await pending; });
  expect(result.current.gallery).toBeNull();
});
it("ignores receipts from another conversation or a hidden workspace", async () => {
  const get = vi.spyOn(api, "asset");
  const { result } = renderHook(() => useAssetPresentation("p", "another-chat", false));
  await act(async () => result.current.present(message("reply")));
  expect(get).not.toHaveBeenCalled();
});

const controlMessage = (id: string, action: Record<string, unknown>) => ({ id, role: "assistant", conversation_id: "chat", metadata: { presentation_actions: [{ project_id: "p", ...action }] } } as unknown as Message);

it("exposes the actual numbered gallery order and selects without re-fetching originals", async () => {
  const get = vi.spyOn(api, "asset").mockImplementation(async id => asset(id));
  const { result } = renderHook(() => useAssetPresentation("p", "chat", true));
  await act(async () => result.current.present(controlMessage("gallery", { action: "gallery", asset_ids: ["b", "a"] })));
  expect(result.current.context()).toEqual({ asset_ids: ["b", "a"], index: 0, mode: "gallery" });
  await act(async () => result.current.present(controlMessage("choose", { action: "select", asset_ids: ["b", "a"], index: 1 })));
  expect(result.current.gallery?.assets[result.current.gallery.index].id).toBe("a");
  expect(result.current.context()?.mode).toBe("viewer");
  expect(get).toHaveBeenCalledTimes(2);
  act(() => result.current.browse());
  expect(result.current.context()?.mode).toBe("gallery");
});

it("targets playback at the selected video and deduplicates commands", async () => {
  vi.spyOn(api, "asset").mockResolvedValue({ ...asset("v"), kind: "video" });
  const { result } = renderHook(() => useAssetPresentation("p", "chat", true));
  await act(async () => result.current.present(controlMessage("open", { action: "open", asset_ids: ["v"], autoplay: true })));
  expect(result.current.playback).toMatchObject({ assetId: "v", action: "play" });
  const pause = controlMessage("pause", { action: "pause", asset_ids: ["v"] });
  await act(async () => result.current.present(pause));
  expect(result.current.playback?.action).toBe("pause");
  await act(async () => result.current.present(controlMessage("seek", { action: "seek", asset_ids: ["v"], seconds: -10 })));
  expect(result.current.playback?.seconds).toBe(-10);
  await act(async () => result.current.present(pause));
  expect(result.current.playback?.action).toBe("seek");
  act(() => result.current.close());
  expect(result.current.context()).toBeNull(); expect(result.current.playback).toBeNull();
});

it("never reopens a closed or changed gallery from a late numbered selection", async () => {
  const get = vi.spyOn(api, "asset").mockResolvedValue(asset("a"));
  const { result } = renderHook(() => useAssetPresentation("p", "chat", true));
  await act(async () => result.current.present(controlMessage("open", { action: "gallery", asset_ids: ["a"] })));
  act(() => result.current.close());
  await act(async () => result.current.present(controlMessage("late", { action: "select", asset_ids: ["a"], index: 0 })));
  expect(result.current.gallery).toBeNull(); expect(get).toHaveBeenCalledTimes(1);
  expect(result.current.error).toContain("gallery changed");
});

it("rejects playback for an image and for a video other than the visible one", async () => {
  vi.spyOn(api, "asset").mockResolvedValue(asset("a"));
  const { result } = renderHook(() => useAssetPresentation("p", "chat", true));
  await act(async () => result.current.present(message("open")));
  await act(async () => result.current.present(controlMessage("bad", { action: "play", asset_ids: ["another-video"] })));
  expect(result.current.playback).toBeNull(); expect(result.current.error).toContain("video changed");
});

it("allows an open and playback receipt in one response without reading stale state", async () => {
  vi.spyOn(api, "asset").mockResolvedValue({ ...asset("v"), kind: "video" });
  const { result } = renderHook(() => useAssetPresentation("p", "chat", true));
  const reply = controlMessage("compound", { action: "open", asset_ids: ["v"] });
  (reply.metadata.presentation_actions as object[]).push({ action: "play", project_id: "p", asset_ids: ["v"] });
  await act(async () => result.current.present(reply));
  expect(result.current.playback).toMatchObject({ action: "play", assetId: "v" });
});
