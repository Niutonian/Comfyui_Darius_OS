import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Asset } from "@/lib/types";
import { AssetViewer } from "./asset-preview";

const dialogMethods = ["showModal", "close"] as const;
const originalMethods = dialogMethods.map(name => Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name));
afterEach(() => {
  cleanup();
  dialogMethods.forEach((name, index) => {
    const descriptor = originalMethods[index];
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
  });
  vi.restoreAllMocks();
});

function mockModal() {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute("open"); } });
}
const clip = { id: "clip", project_id: "p", kind: "video", metadata: { display_name: "River walk" }, width: 1920, height: 1080 } as unknown as Asset;

it("applies spoken play, pause, seek and stop only to the original media element", async () => {
  mockModal();
  const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  const props = { asset: clip, onSelect: vi.fn(), onClose: vi.fn() };
  const { rerender, unmount } = render(<AssetViewer {...props} playback={{ id: "1", assetId: "clip", action: "play" }} />);
  await waitFor(() => expect(play).toHaveBeenCalledOnce());
  const video = screen.getByLabelText("River walk") as HTMLVideoElement;
  expect(video).toHaveAttribute("src", "/api/darius/api/v1/assets/clip/content");
  Object.defineProperty(video, "duration", { configurable: true, value: 30 });
  video.currentTime = 15;
  rerender(<AssetViewer {...props} playback={{ id: "2", assetId: "clip", action: "seek", seconds: -10 }} />);
  await waitFor(() => expect(video.currentTime).toBe(5));
  rerender(<AssetViewer {...props} playback={{ id: "3", assetId: "clip", action: "pause" }} />);
  await waitFor(() => expect(pause).toHaveBeenCalledOnce());
  rerender(<AssetViewer {...props} playback={{ id: "4", assetId: "clip", action: "stop" }} />);
  await waitFor(() => expect(video.currentTime).toBe(0));
  rerender(<AssetViewer {...props} playback={{ id: "5", assetId: "foreign", action: "play" }} />);
  expect(play).toHaveBeenCalledOnce();
  unmount(); expect(pause).toHaveBeenCalledTimes(3);
});

it("surfaces blocked autoplay with a working tap-to-play fallback and gallery return", async () => {
  mockModal();
  const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockRejectedValueOnce(new DOMException("Autoplay denied", "NotAllowedError")).mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  const browse = vi.fn();
  render(<AssetViewer asset={clip} onSelect={vi.fn()} onClose={vi.fn()} onGallery={browse} playback={{ id: "1", assetId: "clip", action: "play" }} />);
  expect(await screen.findByText(/Your browser blocked playback/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Play" }));
  await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole("button", { name: "Mute" }));
  expect(screen.getByLabelText("River walk")).toHaveProperty("muted", true);
  fireEvent.click(screen.getByRole("button", { name: "Back to gallery" }));
  expect(browse).toHaveBeenCalledOnce();
});

it("shows the fitted original without a size toggle and retains gallery controls", () => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
  const asset: Asset = {
    id: "image-one", project_id: "project-one", kind: "image", role: "generation",
    path: "generated.png", content_hash: "hash", mime_type: "image/png",
    width: 1600, height: 900, duration: null, fps: null, sample_rate: null,
    parent_asset_ids: [], scene_id: null, shot_id: null, provider: "local-comfyui",
    workflow_run_id: null, approval_state: "pending", metadata: { display_name: "Garden" }, created_at: "",
  };
  const next = { ...asset, id: "image-two" };
  const onSelect = vi.fn(), onClose = vi.fn();
  render(<AssetViewer asset={asset} navigationAssets={[asset, next]} onSelect={onSelect} onClose={onClose} />);
  const image = screen.getByRole("img", { name: "Garden" });
  expect(image).toHaveAttribute("src", "/api/darius/api/v1/assets/image-one/content");
  expect(image.parentElement).toHaveClass("fit-size");
  expect(screen.queryByRole("button", { name: /Actual size|Fit to window/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Previous asset" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Next asset" }));
  expect(onSelect).toHaveBeenCalledWith(next);
  fireEvent.click(screen.getByRole("button", { name: "Close asset preview" }));
  expect(onClose).toHaveBeenCalledOnce();
});
