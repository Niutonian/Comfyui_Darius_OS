import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { VideoBoardEditor, VideoBoardControls, VideoCardPreview, videoDefaults, videoModes } from "./video-board";
import { canvasApi, type CanvasDocument, type CanvasGeneration } from "@/lib/canvas-api";
import { request } from "@/lib/api-client";
import { mossApi, type MossBoard, type VideoMode } from "@/lib/moss-workspace";
import type { Asset } from "@/lib/types";

vi.mock("@/lib/api-client", () => ({ request: vi.fn(), api: { assetContentUrl: (id: string) => `/media/${id}` } }));
vi.mock("@/lib/canvas-api", () => ({ canvasApi: { get: vi.fn(), select: vi.fn() } }));
const result = (id = "final-result", status = "completed"): CanvasGeneration => ({ id, revision: 1, jobId: id + "-job", seed: 42, status, statusMessage: status, error: null,
  assetIds: [id + "-video", id + "-intermediate"], createdAt: "2026-10-24", provenance: { profileId: "minimax-h3-reference-video-v1", profileName: "Reference video" } });
const board = (): MossBoard => ({ id: "board", documentId: "document", projectId: "project", name: "Video board", kind: "minimax-h3-video", revision: 2, documentRevision: 2,
  settings: { adapterVersion: "minimax-h3-reference-video-v1", seed: null, references: [], video: { ...videoDefaults(), activeMode: "reference-video" } }, archived: false,
  artboard: { width: 1440, height: 832, preset: "wide" }, prompt: "", regionCount: 0, layout: [], activeResult: null, latest: null, jobs: [], previewAssetId: null, newResult: false });
const document = (generations: CanvasGeneration[] = [], selected: string | null = null) => ({ id: "document", projectId: "project", revision: 2, activeGenerationId: selected, generations } as CanvasDocument);
function show(node: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}>{node}</QueryClientProvider>);
}
const editor = (b = board()) => <VideoBoardEditor board={b} assets={[]} projectId="project" onExit={vi.fn()} onGenerate={vi.fn()} />;
beforeEach(() => {
  vi.mocked(request).mockImplementation(async path => path.includes("derivatives") ? { derivatives: [{ id: "poster", metadata: { derivative_type: "thumbnail" } }] } : { modes: [] });
  vi.mocked(canvasApi.get).mockResolvedValue(document());
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("pins a project video and a separate character image for Body swap without rendering", async () => {
  const b = board(); b.id = "body-swap-media-inputs";
  b.settings = { ...b.settings, adapterVersion: "minimax-h3-body-swap-v1", video: { ...videoDefaults(), activeMode: "body-swap" } };
  const assets = [
    { id: "character", project_id: "project", kind: "image", content_hash: "a".repeat(64), metadata: { display_name: "New character" } },
    { id: "source", project_id: "project", kind: "video", content_hash: "b".repeat(64), metadata: { display_name: "Source performance" } },
    { id: "private", project_id: "other-project", kind: "video", content_hash: "c".repeat(64), metadata: { display_name: "Other project" } },
  ] as unknown as Asset[];
  const save = vi.fn().mockResolvedValue({});
  show(<VideoBoardControls board={b} assets={assets} onChange={save} onError={vi.fn()} />);
  expect(screen.queryByRole("combobox", { name: "Video aspect ratio" })).not.toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Video duration" }).querySelectorAll("option")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Choose source video" }));
  expect(screen.queryByRole("button", { name: "Other project" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Source performance" }));
  fireEvent.click(screen.getByRole("button", { name: "Choose character image" }));
  fireEvent.click(screen.getByRole("button", { name: "New character" }));
  fireEvent.change(screen.getByRole("spinbutton", { name: "Body swap clip start" }), { target: { value: "12.5" } });
  fireEvent.click(screen.getByRole("button", { name: "Save video draft" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  const draft = save.mock.calls[0][0].video.modeDrafts["body-swap"];
  expect(draft).toMatchObject({ seconds: 5, clipStart: 12.5 });
  expect(draft.inputs).toEqual(expect.arrayContaining([
    expect.objectContaining({ assetId: "source", mediaKind: "video", role: "source-video", token: 2 }),
    expect.objectContaining({ assetId: "character", mediaKind: "image", role: "replacement-character", token: 1 }),
  ]));
});

it("switches an older video board to Body swap while retaining its saved scene", async () => {
  const b = board(); b.id = "legacy-body-switch";
  const video = videoDefaults(); video.modeDrafts["reference-video"].prompt = "Keep this existing idea";
  delete (video.modeDrafts as Partial<typeof video.modeDrafts>)["body-swap"];
  b.settings.video = { ...video, activeMode: "reference-video" };
  const save = vi.fn().mockResolvedValue({});
  show(<VideoBoardControls board={b} assets={[]} onChange={save} onError={vi.fn()} />);
  fireEvent.change(screen.getByRole("combobox", { name: "Video mode" }), { target: { value: "body-swap" } });
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][0]).toMatchObject({ adapterVersion: "minimax-h3-body-swap-v1", video: { activeMode: "body-swap", modeDrafts: { "body-swap": { seconds: 5 }, "reference-video": { prompt: "Keep this existing idea" } } } });
});

it("shows the final reference-video result from legacy history when no active selection was saved", async () => {
  vi.mocked(canvasApi.get).mockResolvedValue(document([result()]));
  const { container } = show(editor());
  await waitFor(() => expect(container.querySelector(".h3-viewer > video")).toHaveAttribute("src", "/media/final-result-video"));
  expect(container.querySelector(".h3-viewer > video")).not.toHaveAttribute("src", "/media/final-result-intermediate");
});

it("requests a thumbnail for that same final result on the board card", async () => {
  const b = { ...board(), latest: result() };
  const { container } = show(<VideoCardPreview board={b} />);
  await waitFor(() => expect(container.querySelector("video")).toHaveAttribute("poster", "/media/poster"));
  expect(request).toHaveBeenCalledWith("/assets/final-result-video/derivatives?thumbnail_only=true", { method: "POST" });
});

it("preserves an explicitly selected older video instead of displaying the newest history entry", async () => {
  vi.mocked(canvasApi.get).mockResolvedValue(document([result(), result("chosen")], "chosen"));
  const { container } = show(editor());
  await waitFor(() => expect(container.querySelector(".h3-viewer > video")).toHaveAttribute("src", "/media/chosen-video"));
});

it("does not display a failed intermediate as a finished video", async () => {
  vi.mocked(canvasApi.get).mockResolvedValue(document([{ ...result("failed", "failed"), provenance: { profileId: "minimax-h3-reference-video-v1", partial: true } }]));
  const { container } = show(editor());
  await waitFor(() => expect(canvasApi.get).toHaveBeenCalled());
  expect(container.querySelector(".h3-viewer > video")).toBeNull();
});

it("Choose video inputs opens Board controls after History was closed", async () => {
  show(editor());
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  fireEvent.click(screen.getByRole("button", { name: "Close Canvas utilities" }));
  fireEvent.click(screen.getByRole("button", { name: "Choose video inputs" }));
  expect(screen.getByRole("tab", { name: "Board" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("combobox", { name: "Video mode" })).toBeVisible();
  expect(screen.getByRole("group", { name: "Project image inputs" })).toBeVisible();
});

it("Choose video inputs exits the chat tab and exposes the input controls", async () => {
  function ChatOpenEditor() {
    const [chat, setChat] = useState(true);
    return <VideoBoardEditor board={board()} assets={[]} projectId="project" onExit={vi.fn()} onGenerate={vi.fn()} assistantOpen={chat} onToggleAssistant={() => setChat(value => !value)} />;
  }
  show(<ChatOpenEditor />);
  expect(screen.getByRole("tab", { name: "Chat" })).toHaveAttribute("aria-selected", "true");
  fireEvent.click(screen.getByRole("button", { name: "Choose video inputs" }));
  expect(screen.getByRole("tab", { name: "Board" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("combobox", { name: "Video mode" })).toBeVisible();
  expect(screen.getByRole("group", { name: "Project image inputs" })).toBeVisible();
});

it("the main action opens and focuses the actual chooser when settings are already visible, and binds the selected image", async () => {
  const image: Asset = { id: "project-image", project_id: "project", kind: "image", role: "upload", path: "/mock/project-image.png", content_hash: "a".repeat(64), mime_type: "image/png",
    width: 256, height: 256, duration: null, fps: null, sample_rate: null, parent_asset_ids: [], scene_id: null, shot_id: null, provider: "upload", workflow_run_id: null,
    approval_state: "pending", metadata: { display_name: "A sample image" }, created_at: "2026-10-24" };
  show(<VideoBoardEditor board={board()} assets={[image]} projectId="project" onExit={vi.fn()} onGenerate={vi.fn()} />);
  expect(screen.getByRole("combobox", { name: "Video mode" })).toBeVisible();
  expect(screen.queryByRole("group", { name: "Project image inputs" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Choose video inputs" }));
  const chooser = screen.getByRole("group", { name: "Project image inputs" });
  expect(chooser).toBeVisible();
  await waitFor(() => expect(chooser).toHaveFocus());
  fireEvent.click(screen.getByRole("button", { name: /A sample image/ }));
  expect(screen.getByRole("img", { name: "Picture 1 preview" })).toHaveAttribute("src", "/media/project-image");
  expect(screen.queryByRole("group", { name: "Project image inputs" })).toBeNull();
});

it("reopening the main chooser scrolls and focuses it again", async () => {
  show(editor());
  const action = screen.getByRole("button", { name: "Choose video inputs" });
  fireEvent.click(action);
  const chooser = screen.getByRole("group", { name: "Project image inputs" });
  await waitFor(() => expect(chooser).toHaveFocus());
  fireEvent.click(screen.getByRole("button", { name: "Close Canvas utilities" }));
  action.focus();
  fireEvent.click(action);
  await waitFor(() => expect(chooser).toHaveFocus());
  expect(chooser).toBeVisible();
});

it.each<VideoMode>(["animate-image", "camera-direction", "reference-video"])("saves resolution, aspect ratio and extended duration for %s without rendering", async mode => {
  const b = board();
  b.settings = { ...b.settings, adapterVersion: videoModes.find(m => m.id === mode)!.profile, video: { ...videoDefaults(), activeMode: mode } };
  const save = vi.spyOn(mossApi, "save").mockResolvedValue({ ...b, revision: 3 });
  const generate = vi.fn();
  show(<VideoBoardEditor board={b} assets={[]} projectId="project" onExit={vi.fn()} onGenerate={generate} />);
  expect(screen.getByRole("combobox", { name: "Video duration" }).querySelectorAll("option")).toHaveLength(11);
  fireEvent.change(screen.getByRole("combobox", { name: "Video aspect ratio" }), { target: { value: "vertical" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Video resolution" }), { target: { value: "720p" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Video duration" }), { target: { value: "15" } });
  fireEvent.click(screen.getByRole("button", { name: "Save video draft" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][2]?.video?.modeDrafts[mode]).toMatchObject({ preset: "vertical", resolution: "720p", seconds: 15 });
  expect(generate).not.toHaveBeenCalled();
});
