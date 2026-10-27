import { describe, expect, it } from "vitest";
import { canvasSeed, switchCanvasProfile, MOSS, FIBO_FAST, FIBO_DEV } from "./canvas-profile";

describe("Canvas workflow settings", () => {
  it("preserves large seeds as canonical decimal strings", () => {
    expect(canvasSeed("18446744073709551615", FIBO_DEV)).toBe("18446744073709551615");
    expect(canvasSeed("00064", FIBO_FAST)).toBe("64");
    expect(() => canvasSeed("18446744073709551616", FIBO_DEV)).toThrow();
    expect(() => canvasSeed("4294967296", MOSS)).toThrow();
  });
  it("keeps each profile's seed when switching without mutating the layout", () => {
    const moss = { adapterVersion: MOSS, seed: 42, references: [] } as const;
    const fast = switchCanvasProfile({ ...moss, references: [] }, FIBO_FAST);
    expect(fast.seed).toBeNull();
    const dev = switchCanvasProfile({ ...fast, seed: "9007199254740999" }, FIBO_DEV);
    expect(switchCanvasProfile(dev, FIBO_FAST).seed).toBe("9007199254740999");
    expect(switchCanvasProfile(dev, MOSS).seed).toBe(42);
  });
});
