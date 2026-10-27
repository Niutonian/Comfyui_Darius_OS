import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import { useDariusStore } from "@/lib/store";
import type { Workflow, RenderPreview } from "@/lib/types";
import { CloudGeneration } from "./cloud-generation";
import { WorkflowJsonInput } from "./workflow-json-input";

afterEach(() => vi.restoreAllMocks());
const workflow: Workflow = { id: "bfl-flux-3-image", name: "FLUX 3 Image", version: "1", capability: "text-to-image", execution_provider: "bfl", workflow_reference: "flux-3-image", required_inputs: [{ key: "prompt", type: "string", required: true, description: "Visual subject" }, { key: "images", type: "json", required: false, description: "References" }], output: { kind: "image", count: 1 }, estimated_vram_gb: null, estimated_cost: null, requires_approval: true, enabled: true };
const preview: RenderPreview = { workflow_id: workflow.id, workflow_name: workflow.name, origin_workflow_id: null, provider: "bfl", verification: "contract", graph_digest: null, positive: [{ slot: "prompt", label: "Prompt", value: "Garvin in the vat bay" }], negative: [], models: [], image_inputs: [], reference_asset_ids: [], warnings: [], blocked: false };

it("reviews cloud settings without submitting or approving a paid job", async () => {
  const user = userEvent.setup();
  useDariusStore.setState({ activeProjectId: "project" });
  vi.spyOn(api, "workflows").mockResolvedValue([workflow]);
  vi.spyOn(api, "workflowInputOptions").mockResolvedValue({});
  vi.spyOn(api, "previewWorkflow").mockResolvedValue(preview);
  const propose = vi.spyOn(api, "proposeWorkflow");
  const approve = vi.spyOn(api, "approveActionPlan");
  const check = vi.spyOn(api, "bflConnection").mockResolvedValue({ configured: true, authenticated: true, credits_available: true });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><CloudGeneration projectId="project" assets={[]} /></QueryClientProvider>);
  await screen.findByRole("option", { name: "FLUX 3 Image" });
  expect(check).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Check connection" }));
  expect(await screen.findByText("API key accepted · credits available.")).toBeVisible();
  await user.type(screen.getByRole("textbox", { name: "Visual prompt / edit instruction" }), "Garvin in the vat bay");
  await user.click(screen.getByRole("button", { name: "Review cloud generation" }));
  expect(await screen.findByText(/Paid BFL API request/)).toBeVisible();
  expect(propose).not.toHaveBeenCalled();
  expect(approve).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Edit settings" }));
  const json = screen.getByRole("textbox", { name: /^Images/ });
  fireEvent.change(json, { target: { value: "{invalid json" } });
  expect(await screen.findByText(/Enter valid JSON before reviewing/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Create action plan" })).toBeDisabled();
});

it("keeps invalid JSON editable without replacing it with the last valid value", () => {
  const change = vi.fn();
  const invalid = vi.fn();
  render(<WorkflowJsonInput value={["asset:first"]} disabled={false} onChange={change} onInvalid={invalid} />);
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "[" } });
  expect(input).toHaveValue("[");
  expect(invalid).toHaveBeenLastCalledWith(true);
  expect(change).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: '[[0,"asset:first"],[8,"asset:last"]]' } });
  expect(change).toHaveBeenLastCalledWith([[0, "asset:first"], [8, "asset:last"]]);
  expect(invalid).toHaveBeenLastCalledWith(false);
});
