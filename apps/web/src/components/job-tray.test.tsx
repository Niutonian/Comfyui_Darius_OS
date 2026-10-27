import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import { useDariusStore } from "@/lib/store";
import type { Job } from "@/lib/types";
import { JobTray } from "./job-tray";

const job = { id: "d596131d-fixture", project_id: "p", job_type: "timeline_render", provider: "ffmpeg", status: "queued", progress: 0, status_message: "Approved render queued", created_at: "2026-10-18T00:00:00Z" } as Job;
beforeEach(() => useDariusStore.setState({ trayOpen: true, selection: null }));
afterEach(() => vi.restoreAllMocks());
function show(jobs: Job[] = [job]) { return render(<QueryClientProvider client={new QueryClient()}><JobTray jobs={jobs} hasError={false} /></QueryClientProvider>); }

it("starts only queued timeline renders without selecting/closing the job row", async () => {
  const user = userEvent.setup();
  const start = vi.spyOn(api, "startRenderJob").mockResolvedValue({ ...job, status: "running" });
  show([job, { ...job, id: "generation", job_type: "generation" }, { ...job, id: "completed", status: "completed" }]);
  expect(screen.getAllByRole("button", { name: /^Start render / })).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Start render d596131d" }));
  await waitFor(() => expect(start).toHaveBeenCalledExactlyOnceWith(job.id));
  expect(useDariusStore.getState().selection).toBeNull();
  expect(useDariusStore.getState().trayOpen).toBe(true);
});

it("supports keyboard activation and reports a failed request with a retryable button", async () => {
  const user = userEvent.setup();
  const start = vi.spyOn(api, "startRenderJob").mockRejectedValue(new Error("Worker could not start"));
  show();
  const button = screen.getByRole("button", { name: "Start render d596131d" });
  button.focus(); await user.keyboard(" ");
  expect(await screen.findByRole("alert")).toHaveTextContent("Worker could not start");
  expect(button).toBeEnabled(); expect(start).toHaveBeenCalledOnce();
  expect(useDariusStore.getState().selection).toBeNull();
});

it("prevents duplicate clicks while starting a render", async () => {
  const user = userEvent.setup();
  let done!: (job: Job) => void;
  const start = vi.spyOn(api, "startRenderJob").mockImplementation(() => new Promise((resolve) => { done = resolve; }));
  show();
  const button = screen.getByRole("button", { name: "Start render d596131d" });
  await user.click(button); await user.click(button);
  expect(button).toBeDisabled(); expect(start).toHaveBeenCalledOnce();
  done(job); await waitFor(() => expect(button).toBeEnabled());
});
