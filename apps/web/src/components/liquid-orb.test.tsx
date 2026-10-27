import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiquidOrb } from "./liquid-orb";

describe("LiquidOrb presence", () => {
  it("exposes the current Darius mood for thought states", () => {
    const { rerender, container } = render(<LiquidOrb mood="thinking" size="thought" />);
    const orb = container.querySelector(".liquid-orb");
    expect(orb).toHaveAttribute("data-mood", "thinking");
    expect(orb).toHaveClass("mood-thinking", "size-thought");
    rerender(<LiquidOrb mood="listening" size="mark" />);
    expect(container.querySelector(".liquid-orb")).toHaveAttribute("data-mood", "listening");
    expect(container.querySelector(".liquid-orb")).toHaveClass("size-mark");
  });
});
