import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { canvasApi } from "./canvas-api";
import { prepareBoard, mossApi, fitPlacements, worldPoint, fitCardToArtwork, boardStatus, type MossBoard, type CanvasDraft } from "./moss-workspace";
import { emptyCanvas } from "./canvas-document";
import { rememberWorkspaceValue, readWorkspaceValue } from "./workspace-session";
import { loadCanvasIntent, saveCanvasIntent } from "./canvas-intent";

const board = { id: "board-a", projectId: "p", documentId: "doc-a", revision: 1, documentRevision: 1, name: "A", settings: { adapterVersion: "moss-bboxes-v1", seed: 42, references: [] }, jobs: [], activeResult: null, latest: null } as unknown as MossBoard;
beforeEach(() => sessionStorage.clear());
afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });
it("fits and reverses only workspace coordinates, independent of semantic dimensions", () => {
  const placements = [{ boardId: "a", x: -300, y: 200, displayWidth: 360, displayHeight: 450, order: 0 }, { boardId: "b", x: 300, y: 200, displayWidth: 360, displayHeight: 450, order: 1 }];
  const original = structuredClone(placements), camera = fitPlacements(placements, { width: 1400, height: 850 });
  expect(camera.scale).toBeGreaterThan(0);
  expect(worldPoint({ x: camera.x - 300*camera.scale, y: camera.y + 200*camera.scale }, camera)).toEqual({ x: -300, y: 200 });
  expect(placements).toEqual(original);
});
it("fits landscape and portrait cards to artwork without changing their position or document", () => {
  const placement = { boardId: "a", x: -300, y: 200, displayWidth: 360, displayHeight: 450, order: 2 };
  const artwork = { width: 1360, height: 768 }, original = structuredClone(artwork);
  const landscape = fitCardToArtwork(placement, artwork);
  expect(landscape.displayWidth / (landscape.displayHeight - 92)).toBeCloseTo(1360 / 768);
  expect(landscape).toMatchObject({ boardId: "a", x: -300, y: 200, order: 2 });
  const portrait = fitCardToArtwork(placement, { width: 768, height: 1360 });
  expect(portrait.displayWidth).toBe(360);
  expect(portrait.displayWidth / (portrait.displayHeight - 92)).toBeCloseTo(768 / 1360);
  expect(artwork).toEqual(original); expect(placement.displayHeight).toBe(450);
  expect(fitCardToArtwork(placement, { width: 10000, height: 100 })).toMatchObject({ displayWidth: 800, displayHeight: 350 });
});
it("saves an unmounted board's draft without touching another board", async () => {
  const saved = emptyCanvas(), edited = { ...saved, name: "A edited", globalPrompt: "A red cube" };
  const draft: CanvasDraft = { revision: 1, saved, history: { past: [], present: edited, future: [] } };
  rememberWorkspaceValue("canvas:p:doc-a:draft", draft);
  rememberWorkspaceValue("canvas:p:doc-b:draft", "B is independent");
  vi.spyOn(canvasApi, "save").mockResolvedValue({ id: "doc-a", projectId: "p", revision: 2, content: edited, generations: [], activeGenerationId: null, updatedAt: "" });
  vi.spyOn(canvasApi, "get").mockResolvedValue({ id: "doc-a", projectId: "p", revision: 2, content: edited, generations: [], activeGenerationId: null, updatedAt: "" });
  const target = await prepareBoard("p", board);
  expect(target).toMatchObject({ boardId: "board-a", documentId: "doc-a", documentRevision: 2, name: "A edited" });
  expect(readWorkspaceValue("canvas:p:doc-b:draft")).toBe("B is independent");
  expect(readWorkspaceValue<CanvasDraft>("canvas:p:doc-a:draft")?.saved).toEqual(edited);
});
it("reconciles a clean remembered document with a newer saved rename", async () => {
  const saved = emptyCanvas(), remote = { ...saved, name: "Renamed from overview" };
  rememberWorkspaceValue("canvas:p:doc-a:draft", { revision: 1, saved, history: { past: [], present: saved, future: [] } });
  vi.spyOn(canvasApi, "get").mockResolvedValue({ id: "doc-a", projectId: "p", revision: 3, content: remote, generations: [], activeGenerationId: null, updatedAt: "" });
  expect(await prepareBoard("p", board)).toMatchObject({ documentRevision: 3, name: remote.name });
});
it("retains transport identity through a reload without storing document contents", () => {
  const intent = { documentId: "doc-a", boardId: "board-a", boardRevision: 2, revision: 3, key: "same-request", seed: 42 };
  saveCanvasIntent("p", "doc-a", intent);
  expect(loadCanvasIntent("p", "doc-a")).toEqual(intent);
  expect(loadCanvasIntent("other-project", "doc-a")).toBeUndefined();
  expect(sessionStorage.getItem("darius-canvas-intent:p:doc-a")).not.toContain("globalPrompt");
  saveCanvasIntent("p", "doc-a"); expect(loadCanvasIntent("p", "doc-a")).toBeUndefined();
});
it("maps badges from durable records and keeps preparation separate", () => {
  expect(boardStatus(board)).toBe("Draft"); expect(boardStatus(board, true)).toBe("Preparing");
  expect(boardStatus({ ...board, jobs: [{ status: "queued" }] as MossBoard["jobs"] })).toBe("Queued");
  expect(boardStatus({ ...board, jobs: [{ status: "running" }] as MossBoard["jobs"] })).toBe("Running");
  expect(boardStatus(board, false, "Preflight rejected")).toBe("Needs attention");
  expect(boardStatus({ ...board, newResult: true })).toBe("New result");
  expect(boardStatus({ ...board, jobs: [{ status: "queued" }] as MossBoard["jobs"] }, false, "Worker could not start")).toBe("Queued");
});

it("flushes a pending video draft before capturing its board revision without generating", async () => {
  const draft = { schemaVersion: 1, family: "minimax-h3", activeMode: "animate-image", modeDrafts: { "body-swap": { prompt: "", inputs: [], camera: "", audio: "", seconds: 5, turbo: true }, "animate-image": { prompt: "Saved action", inputs: [], camera: "", audio: "", seconds: 10, turbo: true }, "camera-direction": { prompt: "Retained camera idea", inputs: [], camera: "", audio: "", seconds: 10, turbo: true }, "reference-video": { prompt: "Retained reference idea", inputs: [], camera: "", audio: "", seconds: 10, turbo: true } } } as import("./moss-workspace").VideoConfig;
  const video = { ...board, id: "video", kind: "minimax-h3-video", documentId: "video-doc", settings: { adapterVersion: "minimax-h3-animate-image-v1", seed: null, references: [], video: { ...draft, modeDrafts: { ...draft.modeDrafts, "animate-image": { ...draft.modeDrafts["animate-image"], prompt: "Older action" } } } } } as MossBoard;
  rememberWorkspaceValue("h3:p:video:draft", draft); rememberWorkspaceValue("h3:p:video:base", 1);
  const save = vi.spyOn(mossApi, "save").mockResolvedValue({ ...video, revision: 2, settings: { ...video.settings, video: draft } });
  vi.spyOn(canvasApi, "get").mockResolvedValue({ id: "video-doc", projectId: "p", revision: 1, content: emptyCanvas(), generations: [], activeGenerationId: null, updatedAt: "" });
  expect(await prepareBoard("p", video)).toMatchObject({ boardId: "video", boardRevision: 2 });
  expect(save).toHaveBeenCalledWith("p", video, expect.objectContaining({ video: draft }));
  expect(draft.modeDrafts["camera-direction"].prompt).toBe("Retained camera idea");
  rememberWorkspaceValue("h3:p:video:base", 0);
  await expect(prepareBoard("p", video)).rejects.toThrow("another device");
});

it("captures the newly saved image profile and full seed before a board request", async () => {
  const saved = { schemaVersion: 1, activeProfile: "flux3-klein-t2i-v1", drafts: { "flux3-klein-t2i-v1": { prompt: "Original idea", seed: null } } } as unknown as import("./moss-workspace").ImageRecipeConfig;
  const edited = { ...saved, activeProfile: "qwen21-edit-v1", drafts: { ...saved.drafts, "qwen21-edit-v1": { prompt: "Keep this subject", seed: "18446744073709551615", inputs: [{ assetId: "exact-version" }] } } } as unknown as import("./moss-workspace").ImageRecipeConfig;
  const image = { ...board, id: "image", kind: "image-recipe", documentId: "image-doc", settings: { adapterVersion: "flux3-klein-t2i-v1", seed: null, references: [], image: saved } } as MossBoard;
  rememberWorkspaceValue("image-recipe:p:image:draft", edited); rememberWorkspaceValue("image-recipe:p:image:base", 1);
  vi.spyOn(mossApi, "save").mockResolvedValue({ ...image, revision: 2, settings: { ...image.settings, adapterVersion: "qwen21-edit-v1", seed: "18446744073709551615", image: edited } });
  vi.spyOn(canvasApi, "get").mockResolvedValue({ id: "image-doc", projectId: "p", revision: 1, content: emptyCanvas(), generations: [], activeGenerationId: null, updatedAt: "" });
  const generate = vi.spyOn(canvasApi, "generate");
  const captured = await prepareBoard("p", image);
  expect(captured).toMatchObject({ boardId: "image", boardRevision: 2, profileId: "qwen21-edit-v1", seed: "18446744073709551615" });
  expect(readWorkspaceValue("image-recipe:p:image:draft")).toBe(edited);
  expect(generate).not.toHaveBeenCalled();
});
