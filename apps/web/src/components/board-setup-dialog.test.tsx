import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BoardSetupDialog } from "./board-setup-dialog";
import { boardSetupApi, requestBoardSetup, type BoardSetup } from "@/lib/board-setup";

afterEach(() => vi.restoreAllMocks());
beforeEach(() => { vi.spyOn(boardSetupApi, 'connection').mockResolvedValue({ root: '', baseUrl: 'http://127.0.0.1:8188', configured: false }); });

const missing: BoardSetup = { profile: "moss-bboxes-v1", state: "needs_setup", planDigest: "a".repeat(64),
  actions: [{ kind: "model", filename: "shared-model.safetensors", size_bytes: 5e9 }], blocked: [] };

it("shows download sizes, requires preparation, then continues only on explicit confirmation", async () => {
  vi.spyOn(boardSetupApi, "check").mockResolvedValue(missing);
  vi.spyOn(boardSetupApi, "status").mockResolvedValue(missing);
  const prepare = vi.spyOn(boardSetupApi, "prepare").mockResolvedValue({ ...missing, state: "ready", message: "Ready" });
  render(<BoardSetupDialog/>);
  let completion: Promise<void>;
  act(() => { completion = requestBoardSetup("moss-bboxes-v1"); });
  expect(await screen.findByText("5.0 GB of model downloads")).toBeInTheDocument();
  expect(prepare).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Prepare board" }));
  await screen.findByRole("button", { name: "Continue generation" });
  expect(prepare).toHaveBeenCalledWith("moss-bboxes-v1", "a".repeat(64), true);
  fireEvent.click(screen.getByRole("button", { name: "Continue generation" }));
  await completion!;
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("shows missing sources as blockers and closing does not install anything", async () => {
  vi.spyOn(boardSetupApi, "check").mockResolvedValue({ ...missing, state: "blocked", blocked: ["Author must supply a model URL"] });
  const prepare = vi.spyOn(boardSetupApi, "prepare");
  render(<BoardSetupDialog/>);
  let completion: Promise<void>;
  act(() => { completion = requestBoardSetup("moss-bboxes-v1").catch(error => { expect(error.status).toBe(409); }); });
  expect(await screen.findByText("Author must supply a model URL")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Prepare board" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close board preparation" }));
  await completion!;
  expect(prepare).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it('lets a failed first setup detect, save and recheck ComfyUI without environment editing', async () => {
  vi.spyOn(boardSetupApi, 'check').mockResolvedValueOnce({ ...missing, state: 'failed', message: 'Connect ComfyUI below' })
    .mockResolvedValue({ ...missing, state: 'checking' });
  vi.spyOn(boardSetupApi, 'status').mockResolvedValue({ ...missing, state: 'failed' });
  const found = { root: 'D:/Comfy Easy/ComfyUI', baseUrl: 'http://127.0.0.1:8188', configured: true };
  const detect = vi.spyOn(boardSetupApi, 'detect').mockResolvedValue(found);
  const save = vi.spyOn(boardSetupApi, 'connect').mockResolvedValue(found);
  render(<BoardSetupDialog/>);
  let completion: Promise<void>;
  act(() => { completion = requestBoardSetup('moss-bboxes-v1').catch(() => {}); });
  await screen.findByText('Connect ComfyUI below');
  fireEvent.click(screen.getByRole('button', { name: 'Detect ComfyUI' }));
  await screen.findByDisplayValue(found.root);
  fireEvent.click(screen.getByRole('button', { name: 'Save connection' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith(found.root, found.baseUrl, ''));
  expect(detect).toHaveBeenCalledWith(found.baseUrl);
  await waitFor(() => expect(boardSetupApi.check).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole('button', { name: 'Close board preparation' }));
  await completion!;
});
