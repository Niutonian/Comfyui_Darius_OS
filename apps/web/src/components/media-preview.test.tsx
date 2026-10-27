import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Asset } from "@/lib/types";
import { MediaPreview } from "./media-preview";

const generatedImage: Asset = {
  id: "asset generated/1",
  project_id: "project-1",
  kind: "image",
  role: "generation",
  path: "E:\\private\\generated.png",
  content_hash: "abcdef123456",
  mime_type: "image/png",
  width: 1024,
  height: 1024,
  duration: null,
  fps: null,
  sample_rate: null,
  parent_asset_ids: [],
  scene_id: null,
  shot_id: null,
  provider: "local-comfyui",
  workflow_run_id: "job-1",
  approval_state: "pending",
  metadata: {},
  created_at: "2026-01-01T00:00:00Z",
};

describe("MediaPreview", () => {
  it("loads generated images through the path-safe backend content route", () => {
    render(<MediaPreview asset={generatedImage} />);

    const image = screen.getByRole("img");
    expect(image).toHaveAttribute(
      "src",
      "/api/darius/api/v1/assets/asset%20generated%2F1/content",
    );
    expect(image).not.toHaveAttribute("src", generatedImage.path);
  });
});
