import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import type { Asset } from "@/lib/types";
import { Composer } from "./composer";

const asset: Asset = {
  id: "asset-uploaded", project_id: "project-1", kind: "image", role: "reference", path: "private/path.png", content_hash: "abcdef123456",
  mime_type: "image/png", width: 100, height: 100, duration: null, fps: null, sample_rate: null, parent_asset_ids: [], scene_id: null,
  shot_id: null, provider: "import", workflow_run_id: null, approval_state: "pending", metadata: {}, created_at: "2026-01-01T00:00:00Z",
};

afterEach(() => vi.restoreAllMocks());
beforeEach(() => { vi.spyOn(api, "localRendering").mockResolvedValue({ enabled: false }); });

describe("Composer media review", () => {
  it("restores text and ready attachments only in their owning conversation without uploading twice", async () => {
    const user = userEvent.setup(); vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:owned-reference"); vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const upload = vi.spyOn(api, "uploadAssetWithProgress").mockResolvedValue(asset);
    function show(draftKey: string) { return render(<QueryClientProvider client={new QueryClient()}><Composer draftKey={draftKey} onSubmit={vi.fn()} projectId="project-1" /></QueryClientProvider>); }
    const original = show("project-1:one");
    await user.type(screen.getByRole("textbox", { name: "Message Darius" }), "Keep my reference");
    await user.upload(original.container.querySelector<HTMLInputElement>('input[type="file"]')!, new File(["x"], "owned.png", { type: "image/png" }));
    await screen.findByText("Immutable asset ready"); original.unmount();
    const other = show("project-1:two"); expect(screen.getByRole("textbox", { name: "Message Darius" })).toHaveValue(""); expect(screen.queryByText("owned.png")).not.toBeInTheDocument(); other.unmount();
    show("project-1:one"); expect(screen.getByRole("textbox", { name: "Message Darius" })).toHaveValue("Keep my reference"); expect(screen.getByText("owned.png")).toBeVisible(); expect(upload).toHaveBeenCalledOnce();
  });
  it("keeps the phone input hidden until requested, preserves hidden drafts, and collapses after sending", async () => {
    const user = userEvent.setup(), onSubmit = vi.fn(), onBeginTyping = vi.fn();
    render(<QueryClientProvider client={new QueryClient()}><Composer compact onBeginTyping={onBeginTyping} onSubmit={onSubmit} projectId="project-1" beforeComposer={<button>Voice session</button>} /></QueryClientProvider>);
    expect(screen.queryByRole("textbox", { name: "Message Darius" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Voice session" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Type a message" }));
    const input = screen.getByRole("textbox", { name: "Message Darius" });
    expect(input).toHaveFocus();
    await user.type(input, "Keep my draft");
    await user.click(screen.getByRole("button", { name: "Hide text input" }));
    expect(screen.queryByRole("textbox", { name: "Message Darius" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue writing" }));
    expect(screen.getByRole("textbox", { name: "Message Darius" })).toHaveValue("Keep my draft");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(onSubmit).toHaveBeenCalledWith("Keep my draft", []);
    expect(screen.queryByRole("textbox", { name: "Message Darius" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Type a message" })).toBeVisible();
    expect(onBeginTyping).toHaveBeenCalledTimes(2);
  });

  it("collapses an empty phone input when leaving it, without submitting anything", async () => {
    const user = userEvent.setup(), submit = vi.fn();
    render(<QueryClientProvider client={new QueryClient()}><Composer compact onSubmit={submit} projectId="project-1" /><button>Elsewhere</button></QueryClientProvider>);
    await user.click(screen.getByRole("button", { name: "Type a message" }));
    await user.click(screen.getByRole("button", { name: "Elsewhere" }));
    expect(screen.queryByRole("textbox", { name: "Message Darius" })).not.toBeInTheDocument();
    expect(submit).not.toHaveBeenCalled();
  });

  it("uploads an attachment with project association before sending its immutable asset", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const upload = vi.spyOn(api, "uploadAssetWithProgress").mockImplementation(async (_file, fields, options) => {
      expect(fields).toMatchObject({ project_id: "project-1", role: "reference" });
      options?.onProgress?.({ loaded: 5, total: 10, percent: 50 });
      return asset;
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(<QueryClientProvider client={client}><Composer onSubmit={onSubmit} projectId="project-1" /></QueryClientProvider>);

    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    await user.upload(input, new File(["image"], "reference.png", { type: "image/png" }));
    expect(await screen.findByText("Immutable asset ready")).toBeInTheDocument();
    expect(upload).toHaveBeenCalledOnce();

    await user.type(screen.getByRole("textbox", { name: "Message Darius" }), "Use this reference");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(onSubmit).toHaveBeenCalledWith("Use this reference", [asset]);
  });

  it("keeps failed uploads reviewable and removable", async () => {
    const user = userEvent.setup();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.spyOn(api, "uploadAssetWithProgress").mockRejectedValue(new Error("nope"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(<QueryClientProvider client={client}><Composer onSubmit={vi.fn()} projectId="project-1" /></QueryClientProvider>);
    await user.upload(container.querySelector<HTMLInputElement>('input[type="file"]')!, new File(["x"], "bad.png", { type: "image/png" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Upload failed");
    await user.click(screen.getByRole("button", { name: "Remove bad.png" }));
    await waitFor(() => expect(screen.queryByText("bad.png")).not.toBeInTheDocument());
  });
});
