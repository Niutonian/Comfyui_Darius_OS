import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { canvasApi, type CanvasGeneration } from "@/lib/canvas-api";
import { ApiError } from "@/lib/api-client";
import { FIBO_FAST } from "@/lib/canvas-profile";
import type { MossBoard } from "@/lib/moss-workspace";
import { CanvasGenerationDetails } from "./canvas-profile-controls";

const board = { id: "board-a", documentId: "document-a", revision: 9, documentRevision: 99, archived: false } as MossBoard;
const source: CanvasGeneration = { id: "preview-a", revision: 2, seed: "18446744073709551615", jobId: "fast-job", status: "completed", statusMessage: "Completed", error: null, assetIds: ["image-a"], createdAt: "2026-10-23",
  provenance: { profileId: FIBO_FAST, profileName: "Fast preview · experimental", compilerVersion: "fibo-layout-string-v1", conditioningPromptVerified: true, documentSnapshot: { globalPrompt: "Historical scene" } } };
beforeEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

it.each([new Error("Connection lost"), new ApiError("Connection lost", 408)])("promotes the historical revision and exact large seed; uncertain retries reuse the saved identity (%s)", async error => {
  const errors: string[] = [], queued = { ...source, id: "dev-a", jobId: "dev-job", status: "queued" };
  const generate = vi.spyOn(canvasApi, "generate").mockRejectedValueOnce(error).mockResolvedValueOnce(queued);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><CanvasGenerationDetails result={source} board={board} projectId="project-a" generations={[source]} onError={error => errors.push(error)} /></QueryClientProvider>);
  expect(generate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Render this preview with Dev" }));
  await waitFor(() => expect(errors).toEqual(["Connection lost"]));
  fireEvent.click(screen.getByRole("button", { name: "Render this preview with Dev" }));
  await screen.findByRole("button", { name: "Dev queued" });
  expect(generate).toHaveBeenCalledTimes(2);
  const first = generate.mock.calls[0], retry = generate.mock.calls[1];
  expect(first).toEqual(retry);
  expect(first.slice(0, 3)).toEqual(["project-a", "document-a", 2]);
  expect(first[4]).toBe("18446744073709551615");
  expect(first[5]).toEqual({ boardId: "board-a", boardRevision: 9, profileId: "fibo-dev-v1", promotedFromGenerationId: "preview-a" });
  expect(screen.getByRole("button", { name: "Dev queued" })).toBeDisabled();
});

it("does not offer promotion for a failed, missing-snapshot or incompatible preview", () => {
  const generate = vi.spyOn(canvasApi, "generate");
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><CanvasGenerationDetails result={{ ...source, provenance: { ...source.provenance, compilerVersion: "future-version" } }} board={board} projectId="project-a" generations={[source]} onError={() => {}} /></QueryClientProvider>);
  expect(screen.getByRole("button", { name: "Render this preview with Dev" })).toBeDisabled();
  expect(generate).not.toHaveBeenCalled();
});
