import { expect, it } from "vitest";
import { imageRecipeDefaults } from "@/components/image-recipe-board";
import { videoDefaults } from "@/components/video-board";
import { acceptsImage, withImageInput, withVideoInput } from "./canvas-drop";
import { IMAGE_EDIT, IMAGE_FLUX } from "./canvas-profile";
import type { MossBoard } from "./moss-workspace";
import type { Asset } from "./types";

const image = (id: string, kind = "image") => ({ id, kind, content_hash: `${id}-hash` }) as Asset;

it("adds a dropped image as the next edit input and switches the board to Edit", () => {
  const first = withImageInput(imageRecipeDefaults(IMAGE_FLUX), image("a"));
  expect(first.ok && first.value.activeProfile).toBe(IMAGE_EDIT);
  const second = first.ok ? withImageInput(first.value, image("b")) : first;
  expect(second.ok && second.value.drafts[IMAGE_EDIT].inputs.map(input => [input.assetId, input.token])).toEqual([["a", 1], ["b", 2]]);
});

it("refuses duplicates, more than ten inputs and anything that is not an image", () => {
  const once = withImageInput(imageRecipeDefaults(IMAGE_EDIT), image("a"));
  expect(once.ok && withImageInput(once.value, image("a")).ok).toBe(false);
  let config = imageRecipeDefaults(IMAGE_EDIT);
  for (let i = 0; i < 10; i++) { const next = withImageInput(config, image(`i${i}`)); if (next.ok) config = next.value; }
  expect(withImageInput(config, image("eleventh")).ok).toBe(false);
  expect(withImageInput(imageRecipeDefaults(IMAGE_EDIT), image("v", "video")).ok).toBe(false);
});

it("binds an image to the video mode's own role and respects its limit", () => {
  const start = withVideoInput(videoDefaults(), image("frame"), "animate-image");
  expect(start.ok && start.value.modeDrafts["animate-image"].inputs[0].role).toBe("starting-frame");
  expect(start.ok && withVideoInput(start.value, image("second"), "animate-image").ok).toBe(false);
  const refs = withVideoInput(videoDefaults(), image("subject"), "reference-video");
  expect(refs.ok && refs.value.activeMode).toBe("reference-video");
  expect(withVideoInput(videoDefaults(), image("x"), "body-swap").ok).toBe(false);
});

it("knows which boards take a dropped image directly", () => {
  expect(acceptsImage({ kind: "minimax-h3-video", settings: {} } as MossBoard)).toBe(true);
  expect(acceptsImage({ kind: "image-recipe", settings: { image: imageRecipeDefaults(IMAGE_EDIT) } } as MossBoard)).toBe(true);
  expect(acceptsImage({ kind: "image-recipe", settings: { image: imageRecipeDefaults(IMAGE_FLUX) } } as MossBoard)).toBe(false);
  expect(acceptsImage({ kind: "moss-t2i", settings: {} } as MossBoard)).toBe(false);
});
