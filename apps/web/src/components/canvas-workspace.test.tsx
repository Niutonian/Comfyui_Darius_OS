import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { canvasApi, type CanvasDocument } from "@/lib/canvas-api";
import { emptyCanvas } from "@/lib/canvas-document";
import { CanvasWorkspace } from "./canvas-workspace";

vi.mock("next/dynamic", () => ({ default: () => function Stage() { return <div data-testid="canvas-stage" />; } }));
vi.mock("@/lib/project-sync", () => ({ subscribeProjectRefresh: () => () => {} }));
vi.mock("@/lib/canvas-api", () => ({ canvasApi: { list: vi.fn(), get: vi.fn(), engine: vi.fn(), save: vi.fn(), generate: vi.fn() } }));
let doc: CanvasDocument;
beforeEach(() => {
  vi.resetAllMocks();
  doc = { id: "canvas-a", projectId: "project-a", revision: 1, content: emptyCanvas(), activeGenerationId: null, updatedAt: "2026-10-22", generations: [] };
  vi.mocked(canvasApi.list).mockResolvedValue([{ id: doc.id, name: doc.content.name, revision: 1, updatedAt: doc.updatedAt }]);
  vi.mocked(canvasApi.get).mockResolvedValue(doc);
  vi.mocked(canvasApi.engine).mockResolvedValue({ adapterVersion: "moss-bboxes-v1", presets: [] });
});
async function open() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><CanvasWorkspace projectId="project-a" assets={[]} /></QueryClientProvider>);
  await screen.findByRole("textbox", { name: "Canvas name" });
  return client;
}

it("identifies a draft without an image as Layout and disables result-dependent modes", async () => {
  await open();
  expect(screen.getByRole("button", { name: "Layout" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Result" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Overlay" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Overlay" })).toHaveAttribute("aria-pressed", "false");
});

it("does not submit an older snapshot when the user edits during save", async () => {
  let finish!: (value: CanvasDocument) => void;
  vi.mocked(canvasApi.save).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await open();
  fireEvent.change(screen.getByRole("textbox", { name: "Canvas name" }), { target: { value: "First edit" } });
  fireEvent.click(screen.getByRole("button", { name: "Generate composition" }));
  await waitFor(() => expect(canvasApi.save).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByRole("textbox", { name: "Canvas name" }), { target: { value: "Newer edit" } });
  await act(async () => finish({ ...doc, revision: 2, content: { ...doc.content, name: "First edit" } }));
  await screen.findByText(/canvas changed while saving/i);
  expect(canvasApi.generate).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox", { name: "Canvas name" })).toHaveValue("Newer edit");
});

it("retains one submission key across an uncertain transport failure", async () => {
  vi.mocked(canvasApi.generate).mockRejectedValueOnce(new TypeError("Network interrupted")).mockRejectedValueOnce(new TypeError("Network interrupted"));
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Generate composition" }));
  await screen.findByText("Network interrupted");
  fireEvent.click(screen.getByRole("button", { name: "Retry submission" }));
  await waitFor(() => expect(canvasApi.generate).toHaveBeenCalledTimes(2));
  expect(vi.mocked(canvasApi.generate).mock.calls[0]).toEqual(vi.mocked(canvasApi.generate).mock.calls[1]);
});

it("keeps the same editable draft through focus mode without unsupported pixel controls", async () => {
  await open();
  fireEvent.change(screen.getByRole("textbox", { name: "Canvas name" }), { target: { value: "My composition" } });
  fireEvent.click(screen.getByRole("button", { name: "Enter canvas focus mode" }));
  expect(screen.getByRole("dialog", { name: "Canvas focus workspace" })).toHaveClass("os-desktop", "space-create");
  expect(screen.getByRole("textbox", { name: "Canvas name" })).toHaveValue("My composition");
  fireEvent.click(screen.getByRole("button", { name: "Exit canvas focus mode" }));
  expect(screen.getByRole("textbox", { name: "Canvas name" })).toHaveValue("My composition");
  expect(screen.queryByText("Protect outside region")).not.toBeInTheDocument();
  expect(canvasApi.generate).not.toHaveBeenCalled();
});
