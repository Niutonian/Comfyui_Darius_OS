import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import { useDariusStore } from "@/lib/store";
import type { Asset } from "@/lib/types";
import { AssistantReferences, ConversationImages } from "./assistant-references";

beforeEach(() => useDariusStore.setState({ referenceAssetIds: [], activeProjectId: "project-a" }));
afterEach(() => vi.restoreAllMocks());

describe("assistant image references", () => {
  it("selects an existing image without re-uploading and removes it", async () => {
    const assets = vi.spyOn(api, "assets").mockResolvedValue([{ id: "image-123", project_id: "project-a", kind: "image", role: "generation", metadata: {} } as Asset]);
    render(<AssistantReferences projectId="project-a" busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Choose project images" }));
    await userEvent.click(await screen.findByRole("button", { name: "Use image Image" }));
    expect(useDariusStore.getState().referenceAssetIds).toEqual(["image-123"]);
    expect(assets).toHaveBeenCalledWith({ project_id: "project-a", kind: "image", limit: 100 });
    await userEvent.click(screen.getByRole("button", { name: "Remove reference image-12" }));
    expect(useDariusStore.getState().referenceAssetIds).toEqual([]);
  });

  it("makes an inspected image selectable and clears references on project change", async () => {
    render(<ConversationImages ids={["image-123"]} />);
    await userEvent.click(screen.getByTitle("Use this image as a reference"));
    expect(useDariusStore.getState().referenceAssetIds).toEqual(["image-123"]);
    useDariusStore.getState().setActiveProject("project-b");
    expect(useDariusStore.getState().referenceAssetIds).toEqual([]);
  });

  it("shows loading errors without pretending the project has no images", async () => {
    vi.spyOn(api, "assets").mockRejectedValue(new Error("API offline"));
    render(<AssistantReferences projectId="project-a" busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Choose project images" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("API offline"));
    expect(screen.queryByText("No project images yet.")).toBeNull();
  });
});
