import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import type { RecipeManifest, Workflow } from "@/lib/types";
import { RecipeRegistration } from "./recipe-registration";

afterEach(() => vi.restoreAllMocks());

const workflow: Workflow = {
  id: "flux.json", name: "FLUX base", version: "folder", capability: "text-to-image",
  execution_provider: "local-comfyui", workflow_reference: "flux.json", required_inputs: [],
  output: { kind: "image", count: 1 }, estimated_cost: null, estimated_vram_gb: null,
  requires_approval: true, enabled: true,
};
const contract: RecipeManifest = {
  workflow_id: workflow.id, version: 1, status: "needs_mapping", graph_digest: "a".repeat(64), source_digest: "b".repeat(64),
  scene_slots: [], protected_slots: ["system.value", "negative.text"], unresolved_slots: ["scene.value", "style.text"], processing_only: false,
  fields: [
    { slot: "scene.value", label: "Scene", value: "", role: "unresolved" },
    { slot: "style.text", label: "Style", value: "Template style", role: "unresolved" },
    { slot: "system.value", label: "Instructions", value: "Expand the user's scene.", role: "system" },
    { slot: "negative.text", label: "Negative", value: "low quality", role: "negative" },
  ],
};

it("registers once, protects instruction fields, and saves explicit scene/preserve roles", async () => {
  const inspect = vi.spyOn(api, "registerRecipe").mockResolvedValue(contract);
  const save = vi.spyOn(api, "saveRecipeMapping").mockResolvedValue({ ...contract, status: "ready", scene_slots: ["scene.value"], unresolved_slots: [], fields: contract.fields.map((field) => field.slot === "scene.value" ? { ...field, role: "scene" } : field.slot === "style.text" ? { ...field, role: "preserve" } : field) });
  const user = userEvent.setup();
  render(<RecipeRegistration workflow={workflow} />);
  expect(inspect).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Register inputs" }));
  expect(await screen.findByText("Protected system instructions")).toBeVisible();
  expect(screen.queryByRole("combobox", { name: /system.value/ })).not.toBeInTheDocument();
  await user.selectOptions(screen.getByRole("combobox", { name: "Role for flux.json scene.value" }), "scene");
  await user.selectOptions(screen.getByRole("combobox", { name: "Role for flux.json style.text" }), "preserve");
  await user.click(screen.getByRole("button", { name: "Save input map" }));
  expect(save).toHaveBeenCalledWith("flux.json", contract.source_digest, { "scene.value": "scene", "style.text": "preserve" });
  expect(await screen.findByText(/Input map saved for this base version/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Close input map" }));
  expect(screen.getByText("Input map ready")).toBeVisible();
});

it("shows registration failures without claiming success", async () => {
  vi.spyOn(api, "registerRecipe").mockRejectedValue(new Error("ComfyUI is unavailable; no render was submitted."));
  render(<RecipeRegistration workflow={workflow} />);
  await userEvent.click(screen.getByRole("button", { name: "Register inputs" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("ComfyUI is unavailable");
  expect(screen.queryByText("Input map ready")).not.toBeInTheDocument();
});
