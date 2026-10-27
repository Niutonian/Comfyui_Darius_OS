import { describe, expect, it } from "vitest";
import type { Workflow } from "./types";
import {
  buildWorkflowInputs,
  primaryPromptInput,
  requestedOutputKind,
  selectWorkflowForPrompt,
  titleCase,
} from "./utils";

const workflow: Workflow = {
  id: "film", name: "Film", version: "1", capability: "text-to-video", execution_provider: "local-comfyui", workflow_reference: "film.json",
  required_inputs: [
    { key: "script", type: "string", required: true, description: "" },
    { key: "seed", type: "integer", required: false, description: "", default: 42 },
  ],
  output: { kind: "video", count: 1 }, estimated_vram_gb: 12, estimated_cost: null, requires_approval: true, enabled: true,
};

const imageWorkflow: Workflow = {
  ...workflow,
  id: "image",
  name: "Local image",
  capability: "text-to-image",
  required_inputs: [{ key: "prompt", type: "string", required: true, description: "" }],
  output: { kind: "image", count: 1 },
};

describe("workflow utilities", () => {
  it("preserves all prepared graph defaults instead of replacing a model filename with the request", () => {
    const prepared: Workflow = { ...workflow, id: "assistant-123", required_inputs: [
      { key: "input_0", type: "string", required: false, description: "Checkpoint", default: "model.safetensors" },
      { key: "input_1", type: "string", required: false, description: "Prompt", default: "Exact prepared prompt" },
    ] };
    expect(buildWorkflowInputs(prepared, "Review my scene")).toEqual({ input_0: "model.safetensors", input_1: "Exact prepared prompt" });
  });
  it("maps conversation intent into semantic required inputs", () => {
    expect(primaryPromptInput(workflow)?.key).toBe("script");
    expect(buildWorkflowInputs(workflow, "A quiet arrival")).toEqual({ script: "A quiet arrival", seed: 42 });
  });

  it("formats contract identifiers for people", () => {
    expect(titleCase("local-comfyui")).toBe("Local Comfyui");
  });

  it("maps uploaded assets into semantic media inputs", () => {
    const mediaWorkflow: Workflow = { ...workflow, required_inputs: [
      { key: "prompt", type: "string", required: true, description: "" },
      { key: "reference", type: "asset:image", required: true, description: "" },
    ] };
    expect(buildWorkflowInputs(mediaWorkflow, "Keep the face", ["asset-1"])).toEqual({ prompt: "Keep the face", reference: "asset-1" });
  });

  it("uses still images as the safe default and only routes explicit motion intent to video", () => {
    expect(requestedOutputKind("Generate a simple image of a lighthouse")).toBe("image");
    expect(requestedOutputKind("A quiet lighthouse at dusk")).toBe("image");
    expect(requestedOutputKind("Animate a moving camera clip of the lighthouse")).toBe("video");
  });

  it("selects text-to-image instead of the first MiniMax video workflow", () => {
    expect(selectWorkflowForPrompt([workflow, imageWorkflow], "Create a simple portrait")?.id).toBe("image");
    expect(selectWorkflowForPrompt([imageWorkflow, workflow], "Generate an animated video")?.id).toBe("film");
  });
});
