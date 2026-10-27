import { expect, it } from "vitest";
import type { Asset, Job } from "./types";
import { assetName, jobName, readableName, spokenText } from "./chat-labels";
import { speechChunks } from "./reply-stream";

const id = "3f6acde7-81fd-4a00-9b23-72aa99d1e0c3";

it("shows names without UUIDs or legacy technical filename suffixes", () => {
  expect(readableName("tommy-forest-3f6acde7-01.png")).toBe("tommy forest 01");
  expect(assetName({ kind: "image", metadata: { display_name: "Tommy — Forest · Image 1" } } as unknown as Asset)).toBe("Tommy — Forest · Image 1");
  expect(jobName({ display_name: "Forest opening shot", job_type: "generation" } as Job)).toBe("Forest opening shot");
  expect(assetName({ kind: "image", metadata: { original_filename: `${id}.png` } } as unknown as Asset)).toBe("Image");
});

it("removes technical IDs only from speech, preserving meaningful numbers and prose", () => {
  const text = `Shot 2, 16:9, 24 fps. Render ${id} is queued. Open tommy-forest-3f6acde7-01.png.`;
  const spoken = spokenText(text);
  expect(spoken).not.toContain(id);
  expect(spoken).not.toContain("3f6acde7");
  expect(spoken).toContain("Shot 2, 16:9, 24 fps.");
  expect(spoken).toContain("tommy forest 01");
  expect(text).toContain(id);
});

it("filters streamed UUIDs even when received in separate deltas", () => {
  let rest = "", said = "";
  const text = `Your image ${id} is ready. It shows Tommy in the forest.`;
  for (const character of text) {
    const split = speechChunks(rest + character); rest = split.rest; said += split.chunks.join(" ");
  }
  said += speechChunks(rest, true).chunks.join(" ");
  expect(said).not.toContain(id);
  expect(said).not.toContain("81fd");
  expect(said).toContain("Tommy in the forest");
});
