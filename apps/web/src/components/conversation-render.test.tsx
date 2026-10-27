import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Asset, Job, JobRun } from "@/lib/types";
import { api } from "@/lib/api-client";
import { useKnownAssets } from "@/lib/queries";
import { useRenderJob } from "./render-job-status";
import { ConversationRender, downloadName } from "./conversation-render";
import { useDariusStore } from "@/lib/store";

vi.mock("@/lib/queries", () => ({ useKnownAssets: vi.fn() }));
vi.mock("./render-job-status", async original => ({ ...await original<typeof import("./render-job-status")>(), useRenderJob: vi.fn() }));
vi.mock("./asset-preview", () => ({ AssetPreview: ({ asset }: { asset: Asset }) => <button>Full size {asset.id}</button> }));
const asset = { id: "forest", project_id: "p", role: "generation", kind: "image", mime_type: "image/png", metadata: { display_name: "Forest opening" }, width: 1600, height: 900 } as unknown as Asset;
const job = { id: "job", project_id: "p", display_name: "Forest opening", status: "completed", output_asset_ids: [asset.id] } as unknown as Job;
beforeEach(() => {
  useDariusStore.setState({ activeProjectId: "p", referenceAssetIds: ["old-reference"] });
  vi.mocked(useRenderJob).mockReturnValue({ data: job, isError: false } as ReturnType<typeof useRenderJob>);
  vi.mocked(useKnownAssets).mockReturnValue({ assets: [asset, { ...asset, id: "foreign", project_id: "other" }] } as ReturnType<typeof useKnownAssets>);
});

it("can explicitly use the output for the next voice message without rendering", async () => {
  const user = userEvent.setup(), generate = vi.spyOn(api, "assistantReplyStream");
  render(<ConversationRender jobId="job" projectId="p" />);
  await user.click(screen.getByRole("button", { name: "Use as reference" }));
  expect(useDariusStore.getState().referenceAssetIds).toEqual(["forest"]);
  expect(screen.getByRole("button", { name: "Use as reference" })).toHaveAttribute("aria-pressed", "true");
  expect(generate).not.toHaveBeenCalled();
});
afterEach(() => vi.restoreAllMocks());

it("shows one named result with contextual actions and a readable original download", async () => {
  const user = userEvent.setup(), followup = vi.fn(), generate = vi.spyOn(api, "assistantReplyStream");
  render(<ConversationRender jobId="job" projectId="p" onFollowup={followup} />);
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("download", "Forest opening.png");
  expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", expect.stringContaining("/assets/forest/content"));
  await user.click(screen.getByRole("button", { name: "Animate" }));
  expect(followup).toHaveBeenCalledWith(asset, "animate");
  expect(generate).not.toHaveBeenCalled();
});

it("offers read-only retry guidance and never retries an uncertain render automatically", async () => {
  const user = userEvent.setup();
  vi.mocked(useRenderJob).mockReturnValue({ data: { ...job, status: "failed", output_asset_ids: [] }, isError: false } as unknown as ReturnType<typeof useRenderJob>);
  vi.mocked(useKnownAssets).mockReturnValue({ assets: [] } as unknown as ReturnType<typeof useKnownAssets>);
  const inspect = vi.spyOn(api, "jobRun").mockResolvedValue({ job_id: "job", can_retry: false, recovery_message: "The provider may still be working. Check its history." } as JobRun);
  const retry = vi.spyOn(api, "retryJob");
  render(<ConversationRender jobId="job" projectId="p" />);
  await user.click(screen.getByRole("button", { name: "Retry options" }));
  expect(await screen.findByText(/provider may still be working/)).toBeVisible();
  expect(inspect).toHaveBeenCalledWith("job");
  expect(retry).not.toHaveBeenCalled();
});

it("keeps action buttons disabled while another request is working", () => {
  render(<ConversationRender jobId="job" projectId="p" busy onFollowup={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Upscale" })).toBeDisabled();
});

it("sanitizes download filenames without changing asset IDs or URLs", () => {
  expect(downloadName({ ...asset, metadata: { display_name: "Forest / night: take?" } })).toBe("Forest - night- take-.png");
  expect(asset.id).toBe("forest");
});
