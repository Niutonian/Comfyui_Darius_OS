import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import { queryKeys } from "@/lib/queries";
import type { Asset, Job, Message } from "@/lib/types";
import { messageJobIds, RenderJobStatus, RenderMessageText, RenderResultButton } from "./render-job-status";

vi.mock("./asset-preview", () => ({ AssetViewer: ({ asset, onClose }: { asset: Asset; onClose: () => void }) => <div role="dialog" aria-label={`Original ${asset.id}`}><button onClick={onClose}>Close original</button></div> }));
const queued = { id: "d596131d-full", project_id: "p", job_type: "timeline_render", provider: "ffmpeg", status: "queued", progress: 0, output_asset_ids: [], status_message: "queued; start the worker to execute it." } as unknown as Job;
const completed = { ...queued, status: "completed", progress: 1, output_asset_ids: ["original"] };
afterEach(() => vi.restoreAllMocks());

it("updates the same receipt through running and completed without starting/retrying a job", async () => {
  const read = vi.spyOn(api, "job").mockResolvedValue(queued);
  const start = vi.spyOn(api, "startRenderJob"), retry = vi.spyOn(api, "retryJob");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><RenderJobStatus jobId={queued.id} projectId="p" /></QueryClientProvider>);
  expect(await screen.findByText(/Queued · waiting for a worker/)).toBeVisible();
  expect(screen.queryByText(/start the worker to execute/)).not.toBeInTheDocument();
  read.mockResolvedValue({ ...queued, status: "running", progress: .4 });
  await act(() => client.invalidateQueries({ queryKey: queryKeys.job(queued.id) }));
  expect(await screen.findByText(/Rendering · 40%/)).toBeVisible();
  read.mockResolvedValue(completed);
  await act(() => client.invalidateQueries({ queryKey: queryKeys.job(queued.id) }));
  expect(await screen.findByText(/Completed · 100%/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Open result" })).toBeEnabled();
  expect(start).not.toHaveBeenCalled(); expect(retry).not.toHaveBeenCalled();
});

it("replaces saved receipt prose, but preserves user quotes and assistant narrative", async () => {
  vi.spyOn(api, "job").mockResolvedValue(completed);
  const message = { role: "assistant", content: "Render job d596131d queued; start the worker to execute it.", metadata: { job_id: queued.id } } as unknown as Message;
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><RenderMessageText message={message} projectId="p" /><RenderMessageText message={{ ...message, role: "user" }} projectId="p" /><RenderMessageText message={{ ...message, content: "Render jobs are useful for this project." }} projectId="p" /></QueryClientProvider>);
  expect(await screen.findByText(/Completed · 100%/)).toBeVisible();
  expect(screen.getAllByText(message.content)).toHaveLength(1);
  expect(screen.getByText("Render jobs are useful for this project.")).toBeVisible();
});

it("opens the original only after a click, and rejects a foreign-project output", async () => {
  const user = userEvent.setup();
  const read = vi.spyOn(api, "asset").mockResolvedValue({ id: "original", project_id: "p", kind: "video" } as Asset);
  render(<RenderResultButton job={completed} projectId="p" />);
  expect(read).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Open result" }));
  expect(await screen.findByRole("dialog", { name: "Original original" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Close original" }));
  read.mockResolvedValue({ id: "original", project_id: "other", kind: "video" } as Asset);
  await user.click(screen.getByRole("button", { name: "Open result" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable in the current project/);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("shows refresh failure honestly rather than a stale successful status", async () => {
  vi.spyOn(api, "job").mockRejectedValue(new Error("Offline"));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><RenderJobStatus jobId={queued.id} projectId="p" initialJob={completed} /></QueryClientProvider>);
  await waitFor(() => expect(screen.getByText(/last status may be outdated/)).toBeVisible(), { timeout: 2500 });
  expect(screen.getByRole("button", { name: "Refresh render status" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "Open result" })).not.toBeInTheDocument();
});

it("collects distinct jobs from multi-shot and local render receipts", () => {
  expect(messageJobIds({ job_id: "a", local_render_job_ids: ["a", "b"], generation_drafts: [{ job_id: "c" }, { job_id: null }] })).toEqual(["a", "b", "c"]);
});

it("shows live completion after manual review and retains the old draft reply as history", async () => {
  vi.spyOn(api, "job").mockResolvedValue(completed);
  const message = { role: "assistant", content: "Ready for review. No render was submitted.",
    metadata: { job_id: queued.id, reviewed_generation: true } } as unknown as Message;
  render(<QueryClientProvider client={new QueryClient()}><RenderMessageText message={message} projectId="p" /></QueryClientProvider>);
  expect(await screen.findByText(/Completed · 100%/)).toBeVisible();
  expect(screen.getByText("Original reply before approval")).toBeVisible();
  expect(screen.getByText(message.content)).not.toBeVisible();
});
