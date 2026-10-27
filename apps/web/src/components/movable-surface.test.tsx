import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it } from "vitest";
import { MovableSurface } from "./movable-surface";

function Draft() { const [value, setValue] = useState(""); return <input aria-label="Draft" value={value} onChange={(event) => setValue(event.target.value)} />; }
it("keeps the same input and unsent draft when moving into and out of an editor drawer", async () => {
  const user = userEvent.setup();
  const drawer = document.createElement("div"); document.body.appendChild(drawer);
  const { rerender, unmount } = render(<MovableSurface><Draft /></MovableSurface>);
  const input = await screen.findByRole("textbox", { name: "Draft" });
  await user.type(input, "Keep my unsent text");
  rerender(<MovableSurface target={drawer}><Draft /></MovableSurface>);
  await waitFor(() => expect(drawer.contains(input)).toBe(true));
  expect(input).toHaveValue("Keep my unsent text");
  expect(input).toHaveFocus();
  rerender(<MovableSurface><Draft /></MovableSurface>);
  await waitFor(() => expect(drawer.contains(input)).toBe(false));
  expect(screen.getByRole("textbox", { name: "Draft" })).toBe(input);
  expect(input).toHaveValue("Keep my unsent text");
  unmount(); drawer.remove();
});
