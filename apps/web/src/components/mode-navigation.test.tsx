import React from "react";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { useDariusStore } from "@/lib/store";
import { ModeNavigation } from "./mode-navigation";

beforeEach(() => useDariusStore.setState({ view: "talk" }));

describe("ModeNavigation", () => {
  it("exposes all four creative spaces and changes the active view", async () => {
    const user = userEvent.setup();
    render(<ModeNavigation />);
    expect(screen.getByRole("button", { name: "Talk" })).toHaveAttribute("aria-current", "page");
    await user.click(screen.getByRole("button", { name: "Map" }));
    expect(useDariusStore.getState().view).toBe("map");
    expect(screen.getByRole("button", { name: "Map" })).toHaveAttribute("aria-current", "page");
  });
});
