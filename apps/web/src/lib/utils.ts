import type { Workflow, WorkflowInput } from "./types";

export function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}

export function titleCase(value: string): string {
  return value.replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function primaryPromptInput(workflow: Workflow): WorkflowInput | undefined {
  if (workflow.execution_provider === "bfl") return workflow.required_inputs.find((input) => input.key === "prompt");
  return workflow.required_inputs.find(
    (input) => input.type === "string" && ["script", "prompt", "motion_prompt"].includes(input.key),
  ) ?? workflow.required_inputs.find((input) => input.type === "string");
}

export function buildWorkflowInputs(workflow: Workflow, prompt: string, assetIds: string[] = []): Record<string, unknown> {
  // A composed graph already contains the assistant's exact inputs. Its prose
  // summary must never replace the first string (which may be a model filename).
  if (workflow.id.startsWith("assistant-")) {
    return Object.fromEntries(workflow.required_inputs.filter((input) => input.default !== null && input.default !== undefined).map((input) => [input.key, input.default]));
  }
  let assetIndex = 0;
  return Object.fromEntries(
    workflow.required_inputs.flatMap((input) => {
      if (workflow.execution_provider === "bfl" && input.type === "json" && ["images", "keyframes"].includes(input.key) && assetIds.length) {
        return [[input.key, assetIds.slice(0, 10).map((id) => `asset:${id}`)]];
      }
      if (input.type === "string") {
        if (workflow.execution_provider === "bfl" && input.key !== "prompt" && input.default == null) return [];
        return [[input.key, input.key === primaryPromptInput(workflow)?.key ? prompt : input.default ?? ""]];
      }
      if (input.type === "asset:image" || input.type === "asset:video") {
        const assetId = assetIds[assetIndex++];
        return assetId ? [[input.key, assetId]] : [];
      }
      if (input.default !== undefined && input.default !== null) return [[input.key, input.default]];
      return [];
    }),
  );
}


const VIDEO_INTENT = /\b(video|clip|animation|animate|animated|motion|moving|footage|movie|timelapse|time-lapse|lip[ -]?sync)\b/i;
const IMAGE_INTENT = /\b(image|picture|photo|photograph|portrait|illustration|artwork|poster|thumbnail|concept art|character sheet|still frame)\b/i;

export function requestedOutputKind(prompt: string, assetKinds: string[] = []): "image" | "video" {
  if (VIDEO_INTENT.test(prompt)) return "video";
  if (IMAGE_INTENT.test(prompt)) return "image";
  if (assetKinds.includes("video")) return "video";
  // A still image is the safer and less expensive default when intent is ambiguous.
  return "image";
}

export function selectWorkflowForPrompt(
  workflows: Workflow[],
  prompt: string,
  assets: Array<{ kind: string }> = [],
): Workflow | undefined {
  const enabled = workflows.filter((workflow) => workflow.enabled);
  const kind = requestedOutputKind(prompt, assets.map((asset) => asset.kind));
  const hasImage = assets.some((asset) => asset.kind === "image");
  const hasVideo = assets.some((asset) => asset.kind === "video");
  const capabilityOrder = kind === "video"
    ? hasVideo
      ? ["video-to-video", "image-to-video", "text-to-video"]
      : hasImage
        ? ["image-to-video", "text-to-video", "video-to-video"]
        : ["text-to-video", "image-to-video", "video-to-video"]
    : hasImage
      ? ["image-to-image", "text-to-image", "character-sheet"]
      : ["text-to-image", "character-sheet", "image-to-image"];

  for (const capability of capabilityOrder) {
    const match = enabled.find(
      (workflow) => workflow.output.kind === kind && workflow.capability === capability,
    );
    if (match) return match;
  }
  return enabled.find((workflow) => workflow.output.kind === kind);
}
