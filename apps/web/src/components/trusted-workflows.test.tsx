import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import type { TrustedWorkflowPreferences, Workflow } from "@/lib/types";
import { TrustedWorkflows } from "./trusted-workflows";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("lets a MiniMax video recipe switch between Generate, Animate and Edit and saves the action", async () => {
  const workflow: Workflow = {
    id: "MiniMax_ref2video.json", name: "MiniMax video", version: "folder",
    capability: "image-to-video", execution_provider: "local-comfyui", workflow_reference: "MiniMax_ref2video.json",
    required_inputs: [], output: { kind: "video", count: 1 }, estimated_cost: null, estimated_vram_gb: null,
    requires_approval: true, enabled: true, assignable_purposes: ["text-to-video", "image-to-video", "video-to-video"],
    input_hints: { image: true, video: true },
  };
  const saved: TrustedWorkflowPreferences = { enabled: true, entries: [{ workflow_id: workflow.id, purpose: "image-to-video", is_default: true }] };
  vi.spyOn(api, "trustedWorkflows").mockResolvedValue(saved);
  vi.spyOn(api, "workflowRecipes").mockResolvedValue({ workflows: [workflow], folder: "workflows/defaults", note: "" });
  const save = vi.spyOn(api, "saveTrustedWorkflows").mockImplementation(async (_, value) => value);
  const user = userEvent.setup();
  render(<TrustedWorkflows projectId="project" />);
  const selector = await screen.findByRole("combobox", { name: "Purpose for MiniMax video" });
  expect(screen.getByRole("option", { name: /^Generate video$/ })).not.toBeDisabled();
  expect(screen.getByRole("option", { name: /^Edit video$/ })).not.toBeDisabled();
  await user.selectOptions(selector, "text-to-video");
  expect(selector).toHaveValue("text-to-video");
  await user.selectOptions(selector, "video-to-video");
  await user.click(screen.getByRole("button", { name: "Save trusted workflows" }));
  expect(save).toHaveBeenCalledWith("project", { enabled: true, entries: [{ workflow_id: workflow.id, purpose: "video-to-video", is_default: true }] });
});

it("edits global defaults without requiring a project", async () => {
  const workflow: Workflow = {
    id: "video.json", name: "Global video base", version: "folder", capability: "text-to-video",
    execution_provider: "local-comfyui", workflow_reference: "video.json", required_inputs: [],
    output: { kind: "video", count: 1 }, estimated_cost: null, estimated_vram_gb: null,
    requires_approval: true, enabled: true, assignable_purposes: ["text-to-video", "image-to-video", "video-to-video"],
  };
  vi.spyOn(api, "globalWorkflowDefaults").mockResolvedValue({ enabled: false, entries: [] });
  const projectLoad = vi.spyOn(api, "trustedWorkflows");
  vi.spyOn(api, "workflowRecipes").mockResolvedValue({ workflows: [workflow], folder: "workflows/defaults", note: "" });
  const save = vi.spyOn(api, "saveGlobalWorkflowDefaults").mockImplementation(async (value) => value);
  const user = userEvent.setup();
  render(<TrustedWorkflows scope="global" />);
  await user.click(await screen.findByRole("checkbox", { name: "Trust Global video base" }));
  await user.click(screen.getByRole("checkbox", { name: "Use global workflow defaults" }));
  await user.click(screen.getByRole("button", { name: "Save global defaults" }));
  expect(projectLoad).not.toHaveBeenCalled();
  expect(save).toHaveBeenCalledWith({ enabled: true, entries: [{ workflow_id: "video.json", purpose: "text-to-video", is_default: true }] });
  expect(await screen.findByText(/Global defaults saved/)).toBeInTheDocument();
});

it("shows inherited global actions in the project panel", async () => {
  vi.spyOn(api, "trustedWorkflows").mockResolvedValue({
    enabled: false, entries: [],
    global_defaults: { enabled: true, entries: [{ workflow_id: "global-video.json", purpose: "text-to-video", is_default: true }] },
  });
  vi.spyOn(api, "workflowRecipes").mockResolvedValue({ workflows: [], folder: "workflows/defaults", note: "" });
  render(<TrustedWorkflows projectId="project" />);
  expect(await screen.findByText("Inherited global recipes")).toBeInTheDocument();
  expect(screen.getByText(/Generate video: global-video.json/)).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Use project workflow overrides" })).not.toBeChecked();
});
