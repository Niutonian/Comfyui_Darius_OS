import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import { useDariusStore } from "@/lib/store";
import type { Asset, TimelineVersion } from "@/lib/types";
import { EditView } from "./edit-view";
import { draftPrefix, type LocalCut } from "@/lib/timeline-draft";

const version: TimelineVersion = {
  id: "version-1", timeline_id: "timeline-1", version_number: 1, state: "draft", edit_summary: "Initial", created_by: "user", created_at: "2026-01-01T00:00:00Z",
  tracks: [{ kind: "video", clips: [
    { id: "clip-a", source_asset_id: "asset-a", source_in: 0, source_out: 5, timeline_in: 0, timeline_out: 5 },
    { id: "clip-b", source_asset_id: "asset-b", source_in: 0, source_out: 4, timeline_in: 5, timeline_out: 9 },
  ] }],
};
let remoteVersion: TimelineVersion | undefined;

vi.mock("@/lib/queries", () => ({
  queryKeys: {
    timelines: (id: string) => ["timelines", id],
    timelineVersions: (id: string) => ["timeline-versions", id],
    job: (id: string) => ["job", id],
  },
  useTimelines: () => ({ data: [{ id: "timeline-1", project_id: "project-1", scene_id: null, name: "Assembly", created_at: "", updated_at: "" }], isLoading: false, error: null }),
  useTimelineVersions: () => ({ data: remoteVersion ? [version, remoteVersion] : [version], isLoading: false }),
}));

const asset = (id: string): Asset => ({
  id, project_id: "project-1", kind: "video", role: "source", path: "private.mp4", content_hash: "abcdef", mime_type: "video/mp4",
  width: 1920, height: 1080, duration: 5, fps: 24, sample_rate: null, parent_asset_ids: [], scene_id: null, shot_id: null,
  provider: "import", workflow_run_id: null, approval_state: "pending", metadata: {}, created_at: "2026-01-01T00:00:00Z",
});

beforeEach(() => {
  localStorage.clear();
  remoteVersion = undefined; useDariusStore.setState({ activeProjectId: "project-1", selection: null });
  vi.spyOn(api, "shotBoard").mockResolvedValue([]);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Edit timeline", () => {
  it("supports trim, split, save and mute shortcuts without capturing typed keys", async () => {
    const user = userEvent.setup();
    const saved = vi.spyOn(api, "createTimelineVersion").mockResolvedValue({ ...version, id: "v2", version_number: 2 });
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><EditView assets={[asset("asset-a"), asset("asset-b")]} /></QueryClientProvider>);
    const timeline = screen.getByRole("region", { name: "Project timeline" });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Edit playhead seconds" }), { target: { value: "2" } });
    fireEvent.keyDown(screen.getByRole("spinbutton", { name: "Trim in (s)" }), { key: "q" });
    expect(screen.getByRole("spinbutton", { name: "Trim in (s)" })).toHaveValue(0);
    fireEvent.keyDown(timeline, { key: "q" });
    expect(screen.getByRole("spinbutton", { name: "Trim in (s)" })).toHaveValue(2);
    fireEvent.keyDown(timeline, { key: "z", ctrlKey: true });
    expect(screen.getByRole("spinbutton", { name: "Trim in (s)" })).toHaveValue(0);
    fireEvent.keyDown(timeline, { key: "s" });
    expect(screen.getByText(/3 clips/)).toBeVisible();
    fireEvent.keyDown(timeline, { key: "m" });
    expect(screen.getByRole("button", { name: "Unmute" })).toBeEnabled();
    fireEvent.keyDown(timeline, { key: "s", ctrlKey: true });
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(saved.mock.calls[0][1].state).toBe("draft");
    await user.click(screen.getByRole("button", { name: "Keyboard shortcuts · ?" }));
    expect(screen.getByRole("region", { name: "Editing keyboard shortcuts" })).toBeVisible();
  });
  it("undoes/redoes edits, keeps native input undo, and branches after undo", async () => {
    const user = userEvent.setup();
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><EditView assets={[asset("asset-a"), asset("asset-b")]} /></QueryClientProvider>);
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Mute" }));
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByRole("button", { name: "Mute" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Redo" }));
    expect(screen.getByRole("button", { name: "Unmute" })).toBeEnabled();
    fireEvent.keyDown(screen.getByRole("spinbutton", { name: "Trim in (s)" }), { key: "z", ctrlKey: true });
    expect(screen.getByRole("button", { name: "Unmute" })).toBeEnabled();
    fireEvent.keyDown(screen.getByRole("button", { name: "Undo" }), { key: "z", ctrlKey: true });
    expect(screen.getByRole("button", { name: "Mute" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Later" }));
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();
  });
  it("recovers an unsaved cut after leaving and reopening Edit without a model or render request", async () => {
    const user = userEvent.setup();
    const createVersion = vi.spyOn(api, "createTimelineVersion");
    const renderJob = vi.spyOn(api, "renderTimeline");
    const client = new QueryClient();
    const ui = () => <QueryClientProvider client={client}><EditView assets={[asset("asset-a"), asset("asset-b")]} /></QueryClientProvider>;
    const first = render(ui());
    await user.click(screen.getByRole("button", { name: "Mute" }));
    first.unmount();
    render(ui());
    expect(screen.getByRole("button", { name: "Unmute" })).toBeEnabled();
    expect(screen.getByText(/Recovered your browser-local cut/)).toBeVisible();
    expect(createVersion).not.toHaveBeenCalled();
    expect(renderJob).not.toHaveBeenCalled();
  });
  it("offers reload recovery explicitly and retains its original base when a remote version arrived", async () => {
    const user = userEvent.setup();
    const cut: LocalCut = { schema: 1, projectId: "project-1", timelineId: "timeline-1", updatedAt: new Date().toISOString(), base: version, baseline: JSON.stringify(version.tracks), tracks: [{ kind: "video", clips: [{ id: "recovered", source_asset_id: "asset-a", source_in: 1, source_out: 5, timeline_in: 0, timeline_out: 4 }] }] };
    const key = draftPrefix("project-1", "timeline-1") + "previous-browser-session";
    localStorage.setItem(key, JSON.stringify(cut));
    remoteVersion = { ...version, id: "remote-v2", version_number: 2 };
    const saved = vi.spyOn(api, "createTimelineVersion").mockResolvedValue({ ...version, id: "v3", version_number: 3 });
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><EditView assets={[asset("asset-a"), asset("asset-b")]} /></QueryClientProvider>);
    expect(screen.getByRole("spinbutton", { name: "Trim in (s)" })).toHaveValue(0);
    await user.click(screen.getByRole("button", { name: "Restore local draft" }));
    expect(screen.getByRole("spinbutton", { name: "Trim in (s)" })).toHaveValue(1);
    expect(screen.getByText(/Your unsaved cut is safe/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Save new version" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(saved.mock.calls[0][1].edit_summary).toContain("Based on v1");
    await waitFor(() => expect(localStorage.getItem(key)).toBeNull());
  });
  it("exposes storage failure instead of promising recovery and preserves the editable cut", async () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => { throw new DOMException("Full", "QuotaExceededError"); });
    const user = userEvent.setup();
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><EditView assets={[asset("asset-a"), asset("asset-b")]} /></QueryClientProvider>);
    await user.click(screen.getByRole("button", { name: "Mute" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/storage blocked or full/);
    expect(screen.getByRole("button", { name: "Unmute" })).toBeEnabled();
  });
  it("splits at a frame-aligned playhead and allows undo and ripple-delete", async () => {
    const user = userEvent.setup();
    const saved = vi.spyOn(api, "createTimelineVersion").mockResolvedValue({ ...version, id: "v2", version_number: 2 });
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><EditView assets={[asset("asset-a"), asset("asset-b")]} /></QueryClientProvider>);
    expect(screen.getByRole("button", { name: "Split selected clip" })).toBeDisabled();
    fireEvent.change(screen.getByRole("spinbutton", { name: "Edit playhead seconds" }), { target: { value: "2" } });
    await user.click(screen.getByRole("button", { name: "Split selected clip" }));
    expect(screen.getByText(/3 clips/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByText(/2 clips/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Redo" }));
    await user.click(screen.getByRole("button", { name: "Ripple delete" }));
    await user.click(screen.getByRole("button", { name: "Save new version" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(saved.mock.calls[0][1].tracks[0]).toMatchObject({ clips: [
      { source_in: 2, source_out: 5, timeline_in: 0, timeline_out: 3 },
      { id: "clip-b", timeline_in: 3, timeline_out: 7 },
    ] });
  });
  it("previews named assets without inserting them and allows the same take to be added twice", async () => {
    const user = userEvent.setup();
    const createVersion = vi.spyOn(api, "createTimelineVersion").mockResolvedValue({ ...version, id: "v2", version_number: 2 });
    const client = new QueryClient();
    const named = { ...asset("asset-a"), metadata: { display_name: "Courtyard take" } };
    render(<QueryClientProvider client={client}><EditView assets={[named, asset("asset-b")]} /></QueryClientProvider>);
    await user.click(screen.getByRole("button", { name: "Preview Courtyard take" }));
    expect(screen.getByRole("region", { name: "Source preview" })).toBeVisible();
    expect(screen.getByText(/2 clips/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add this take" }));
    await user.click(screen.getByRole("button", { name: "Add Courtyard take to timeline" }));
    expect(screen.getByText(/4 clips/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save new version" }));
    await waitFor(() => expect(createVersion).toHaveBeenCalledOnce());
    const clips = (createVersion.mock.calls[0][1].tracks[0] as { clips: Array<{ id: string }> }).clips;
    expect(new Set(clips.map((clip) => clip.id)).size).toBe(4);
  });
  it("keeps unsaved trims when a remote version arrives and saves a separate version", async () => {
    const user = userEvent.setup();
    const createVersion = vi.spyOn(api, "createTimelineVersion").mockResolvedValue({ ...version, id: "own-v3", version_number: 3 });
    const client = new QueryClient();
    const ui = () => <QueryClientProvider client={client}><EditView assets={[asset("asset-a"), asset("asset-b")]} /></QueryClientProvider>;
    const { rerender } = render(ui());
    const trim = screen.getByRole("spinbutton", { name: "Trim in (s)" });
    await user.clear(trim); await user.type(trim, "2");
    remoteVersion = { ...version, id: "remote-v2", version_number: 2, tracks: [{ kind: "video", clips: [{ id: "other-clip", source_asset_id: "asset-b", source_in: 0, source_out: 3, timeline_in: 0, timeline_out: 3 }] }] };
    rerender(ui());
    expect(screen.getByRole("spinbutton", { name: "Trim in (s)" })).toHaveValue(2);
    expect(screen.getByText(/Your unsaved cut is safe/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Save new version" }));
    await waitFor(() => expect(createVersion).toHaveBeenCalledOnce());
    expect(createVersion.mock.calls[0][1].tracks[0]).toMatchObject({ clips: [expect.objectContaining({ id: "clip-a", source_in: 2 }), expect.objectContaining({ id: "clip-b" })] });
    expect(createVersion.mock.calls[0][1].edit_summary).toContain("Based on v1");
  });

  it("automatically adopts a remote version when there is no unsaved edit", () => {
    const client = new QueryClient();
    const ui = () => <QueryClientProvider client={client}><EditView assets={[asset("asset-a"), asset("asset-b")]} /></QueryClientProvider>;
    const { rerender } = render(ui());
    remoteVersion = { ...version, id: "remote-v2", version_number: 2 };
    rerender(ui());
    expect(screen.getByText(/Timeline v2/)).toBeInTheDocument();
    expect(screen.queryByText(/Your unsaved cut is safe/)).not.toBeInTheDocument();
  });
  it("persists an accepted version before explicitly approving a render job", async () => {
    vi.spyOn(api, "job").mockResolvedValue({ id: "job-1", project_id: "project-1", job_type: "timeline_render", status: "queued", progress: 0, output_asset_ids: [] } as unknown as Awaited<ReturnType<typeof api.job>>);
    const user = userEvent.setup();
    const accepted = { ...version, id: "version-accepted", version_number: 2, state: "accepted" };
    const createVersion = vi.spyOn(api, "createTimelineVersion").mockResolvedValue(accepted);
    const renderTimeline = vi.spyOn(api, "renderTimeline").mockResolvedValue({
      id: "job-1", project_id: "project-1", job_type: "timeline_render", provider: "ffmpeg", status: "queued",
      progress: 0, status_message: "queued", output_asset_ids: [], external_job_id: null, error_code: null,
      error_detail: null, attempt_count: 0, retry_of_job_id: null, cancellation_requested: false,
      created_at: "2026-01-01T00:00:00Z", started_at: null, completed_at: null,
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><EditView assets={[asset("asset-a"), asset("asset-b")]} /></QueryClientProvider>);

    await user.click(screen.getByRole("button", { name: "Approve & render" }));

    await waitFor(() => expect(renderTimeline).toHaveBeenCalledWith("timeline-1", "version-accepted", true));
    expect(createVersion).toHaveBeenCalledWith("timeline-1", expect.objectContaining({ state: "accepted" }));
    expect(await screen.findByText(/Timeline export: Queued/)).toBeInTheDocument();
  });

  it("persists trim, reorder, and mute decisions as a new version", async () => {
    const user = userEvent.setup();
    const saved = { ...version, id: "version-2", version_number: 2 };
    const createVersion = vi.spyOn(api, "createTimelineVersion").mockResolvedValue(saved);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><EditView assets={[asset("asset-a"), asset("asset-b")]} /></QueryClientProvider>);

    const trimIn = screen.getByRole("spinbutton", { name: "Trim in (s)" });
    await user.clear(trimIn);
    await user.type(trimIn, "1");
    await user.click(screen.getByRole("button", { name: "Later" }));
    await user.click(screen.getByRole("button", { name: "Mute" }));
    await user.click(screen.getByRole("button", { name: "Save new version" }));

    await waitFor(() => expect(createVersion).toHaveBeenCalledOnce());
    const payload = createVersion.mock.calls[0][1];
    const clips = (payload.tracks[0] as { clips: Array<{ id: string; source_in: number; muted?: boolean }> }).clips;
    expect(clips.map((clip) => clip.id)).toEqual(["clip-b", "clip-a"]);
    expect(clips[1]).toMatchObject({ source_in: 1, muted: true });
    expect(payload.state).toBe("draft");
  });
});
