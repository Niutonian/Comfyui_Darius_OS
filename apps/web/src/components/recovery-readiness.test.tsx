import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { ImageRecipeEditor, imageRecipeDefaults } from "./image-recipe-board";
import { VideoFailureRecovery, VideoBoardEditor, videoDefaults } from "./video-board";
import { readinessItems } from "@/lib/readiness";
import { canvasApi } from "@/lib/canvas-api";
import { mossApi, type MossBoard } from "@/lib/moss-workspace";
import { clearWorkspaceSession } from "@/lib/workspace-session";
import type { Asset, Health } from "@/lib/types";

vi.mock("next/dynamic", () => ({ default: () => function Stage() { return <div data-testid="image-stage" />; } }));
vi.mock("@/lib/api-client", () => ({ request: vi.fn(async () => ({ profiles: [], modes: [] })), api: { assetContentUrl: (id: string) => `/media/${id}` } }));
vi.mock("@/lib/canvas-api", () => ({ canvasApi: { get: vi.fn(), generate: vi.fn() } }));
const base = { id: "board", projectId: "project", documentId: "doc", name: "Edit board", revision: 1, documentRevision: 1, archived: false, jobs: [], latest: null, activeResult: null, previewAssetId: null, artboard: { width: 1024, height: 1024, preset: "square" }, layout: [], regionCount: 0, newResult: false, prompt: "" };
const asset = (id: string, project = "project", role = "generation") => ({ id, project_id: project, kind: "image", role, path: "/fixture.png", mime_type: "image/png", width: 64, height: 64, duration: null, fps: null, sample_rate: null, parent_asset_ids: [], scene_id: null, shot_id: null, provider: "fixture", workflow_run_id: null, approval_state: "pending", created_at: "2026-01-01", content_hash: "a".repeat(64), metadata: { display_name: id } } as Asset);
function show(node: React.ReactNode) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{node}</QueryClientProvider>); }
beforeEach(() => { clearWorkspaceSession(); vi.restoreAllMocks(); vi.mocked(canvasApi.get).mockResolvedValue({ generations: [], activeGenerationId: null } as never); });

it("Qwen Edit main chooser opens project thumbnails, binds the pinned version and never renders", async () => {
 const board = { ...base, kind: "image-recipe", settings: { adapterVersion: "qwen21-edit-v1", references: [], seed: null, image: imageRecipeDefaults("qwen21-edit-v1") } } as MossBoard;
 const generate = vi.fn();
 show(<ImageRecipeEditor board={board} assets={[asset("Selected image"), asset("Foreign image", "another-project"), asset("Thumbnail", "project", "derivative")]} projectId="project" onExit={vi.fn()} onGenerate={generate} onVideo={vi.fn()} />);
 fireEvent.click(screen.getByRole("button", { name: /^Choose image inputs$/ }));
 const picker = screen.getByRole("group", { name: "Project image inputs" });
 expect(picker).toBeVisible();
 expect(screen.queryByRole("button", { name: "Foreign image" })).toBeNull();
 expect(screen.queryByRole("button", { name: "Thumbnail" })).toBeNull();
 fireEvent.click(screen.getByRole("button", { name: "Selected image Selected image" }));
 await waitFor(() => expect(screen.queryByRole("group", { name: "Project image inputs" })).toBeNull());
 expect(screen.getByRole("img", { name: "Image 1" })).toHaveAttribute("src", "/media/Selected image");
 expect(generate).not.toHaveBeenCalled();
});

it("failure recovery exposes an intermediate and requires an explicit recovery choice", () => {
 const recover = vi.fn();
 show(<VideoFailureRecovery generation={{ id: "failed", assetIds: ["preview"], provenance: { partial: true, recovery: { message: "Preview saved; final upscale ran out of GPU memory." } } } as never} onRecover={recover} />);
 expect(screen.getByText("Preview saved; final upscale ran out of GPU memory.")).toBeVisible();
 fireEvent.click(screen.getByRole("button", { name: "Use CPU final upscale" }));
 expect(recover).toHaveBeenCalledWith("cpu");
 expect(canvasApi.generate).not.toHaveBeenCalled();
});

it("loading a CPU recovery draft keeps the failed prompt, references and large seed without submitting", async () => {
 const config = { ...videoDefaults(), activeMode: "reference-video" as const };
 config.modeDrafts['reference-video'].prompt = 'Original scene';
 const board = { ...base, name: "Video", kind: "minimax-h3-video", settings: { adapterVersion: "minimax-h3-reference-video-v1", seed: 1, references: [], video: videoDefaults() } } as MossBoard;
 vi.mocked(canvasApi.get).mockResolvedValue({ generations: [{ id: "failed", status: "failed", seed: "18446744073709551615", error: "OOM", assetIds: ["preview"], provenance: { partial: true, videoConfig: config } }], activeGenerationId: null } as never);
 const save = vi.spyOn(mossApi, "save").mockImplementation(async (_project, current, settings) => ({ ...current, revision: 2, settings: settings! }));
 vi.spyOn(window, "confirm").mockReturnValue(true);
 const generate = vi.fn();
 show(<VideoBoardEditor board={board} assets={[]} projectId="project" onExit={vi.fn()} onGenerate={generate} />);
 fireEvent.click(await screen.findByRole("button", { name: "Use CPU final upscale" }));
 await waitFor(() => expect(save).toHaveBeenCalledOnce());
 const settings = save.mock.calls[0][2]!;
 expect(settings.seed).toBe("18446744073709551615");
 expect(settings.video?.modeDrafts['reference-video']).toMatchObject({ prompt: 'Original scene', upscaleDevice: 'cpu' });
 expect(config.modeDrafts['reference-video'].upscaleDevice).toBeUndefined();
 expect(generate).not.toHaveBeenCalled();
});

it("readiness separates connection, model access and node conflicts while chat stays optional", () => {
 const health: Health = { status: "ok", components: { api: { ready: true }, database: { ready: true }, comfyui: { ready: false }, llm: { ready: false, configured: false } } };
 const rows = readinessItems(health, { profile: 'fibo-dev-v1', state: 'blocked', blocked: ['HF_TOKEN required'] }, { root: '', baseUrl: 'http://127.0.0.1:8188', configured: false });
 expect(rows.find(r => r.name === 'ComfyUI')?.state).toBe('Not configured');
 expect(rows.find(r => r.name === 'Selected board')?.state).toBe('Access required');
 expect(readinessItems(health, { profile: 'fibo-dev-v1', state: 'blocked', blocked: ['node has another revision'] }).find(r => r.name === 'Selected board')?.state).toBe('Incompatible');
 expect(readinessItems(health).find(r => r.name === 'ComfyUI')?.state).toBe('Not running');
 expect(rows.find(r => r.name === 'Chat (optional)')?.hint).toContain('not required for board rendering');
});
