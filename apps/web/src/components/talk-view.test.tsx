import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import { useDariusStore } from "@/lib/store";
import type { ActionPlan, RenderPreview, Workflow } from "@/lib/types";
import { ProposalCard, TalkView } from "./talk-view";

afterEach(() => vi.restoreAllMocks());
const workflow: Workflow = { id: "assistant-test", name: "Scene draft", version: "1", capability: "text-to-image", execution_provider: "local-comfyui", workflow_reference: "fixture.json", required_inputs: [{ key: "prompt", type: "string", required: false, description: "Prompt", default: "Garvin in a spaceship" }], output: { kind: "image", count: 1 }, estimated_vram_gb: null, estimated_cost: null, requires_approval: true, enabled: true };
const preview: RenderPreview = { workflow_id: workflow.id, workflow_name: workflow.name, origin_workflow_id: "qwen-original", provider: "local-comfyui", verification: "graph", graph_digest: "digest", positive: [{ slot: "76.value", label: "Positive", value: "A hedgehog wearing a party hat" }], negative: [{ slot: "100.text", label: "Negative", value: "Garvin in a spaceship" }], models: [{ slot: "4.model", label: "Model", value: "qwen.safetensors" }], image_inputs: [], reference_asset_ids: [], warnings: ["The visual subject is also in negative conditioning."], blocked: true };
function mount(selected = workflow.id) {
  useDariusStore.setState({ activeProjectId: "p" });
  vi.spyOn(api, "workflowInputOptions").mockResolvedValue({});
  const choose = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><TalkView draft={{ id: 1, text: "Garvin in a spaceship", assets: [], projectId: "p" }} workflows={[workflow]} workflowsError={null} workflowsLoading={false} onDismiss={vi.fn()} onRetry={vi.fn()} selectedWorkflowId={selected} setSelectedWorkflowId={choose} /></QueryClientProvider>);
  return choose;
}
it("shows actual connected prompts and model and blocks a corrupt draft", async () => {
  vi.spyOn(api, "previewWorkflow").mockResolvedValue(preview);
  const propose = vi.spyOn(api, "proposeWorkflow");
  mount();
  expect(await screen.findByText("A hedgehog wearing a party hat")).toBeVisible();
  expect(screen.getByText("qwen.safetensors")).toBeVisible();
  expect(screen.getByText("Workflow: qwen-original")).toBeVisible();
  expect(screen.getByRole("button", { name: "Create action plan" })).toBeDisabled();
  expect(propose).not.toHaveBeenCalled();
});
it("requires a successful input inspection before creating a plan", async () => {
  vi.spyOn(api, "previewWorkflow").mockRejectedValue(new Error("Graph missing"));
  mount();
  await screen.findByText(/Could not verify render inputs: Graph missing/);
  expect(screen.getByRole("button", { name: "Create action plan" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Retry input inspection" })).toBeEnabled();
});
it("does not silently select another workflow if the selected one disappears", async () => {
  const user = userEvent.setup();
  const inspect = vi.spyOn(api, "previewWorkflow");
  const choose = mount("deleted-workflow");
  expect(screen.getByText(/No alternative has been selected automatically/)).toBeVisible();
  expect(inspect).not.toHaveBeenCalled();
  expect(choose).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Choose Scene draft" }));
  await waitFor(() => expect(choose).toHaveBeenCalledWith(workflow.id));
});

it("preserves the source message and shows the prepared canvas during review", async () => {
  useDariusStore.setState({ activeProjectId: "p" });
  vi.spyOn(api, "workflowInputOptions").mockResolvedValue({});
  vi.spyOn(api, "previewWorkflow").mockResolvedValue({ ...preview, blocked: false, warnings: [],
    canvases: [{ node_id: "canvas", width: 1280, height: 720 }] });
  const propose = vi.spyOn(api, "proposeWorkflow").mockResolvedValue({
    id: "plan", inputs: {}, expected_output: {}, state: "proposed", provider: "local-comfyui", estimated_cost: null,
  } as unknown as ActionPlan);
  const user = userEvent.setup();
  render(<QueryClientProvider client={new QueryClient()}><ProposalCard workflow={workflow}
    draft={{ id: 2, text: "Albert in the desert", assets: [], projectId: "p", sourceMessageId: "source-user" }}
    onDismiss={vi.fn()} /></QueryClientProvider>);
  expect(await screen.findByText("Image canvas: 1280 × 720")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Create action plan" }));
  await waitFor(() => expect(propose).toHaveBeenCalledWith(workflow.id, expect.objectContaining({
    project_id: "p", source_message_id: "source-user",
  })));
  expect(await screen.findByText("Proposed")).toBeVisible();
});
