import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { Asset } from "@/lib/types";
import { ResultFollowup } from "./result-followup";

const asset = { id: "forest", project_id: "p", kind: "image", metadata: { display_name: "Forest opening" } } as unknown as Asset;
it("stages animation without sending until explicitly submitted", async () => {
  const user = userEvent.setup(), send = vi.fn().mockResolvedValue(undefined), close = vi.fn();
  render(<ResultFollowup draft={{ id: 1, asset, action: "animate" }} busy={false} onSend={send} onClose={close} />);
  expect(send).not.toHaveBeenCalled();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toContain("Animate this image");
  await user.click(screen.getByRole("button", { name: "Send follow-up" }));
  expect(send).toHaveBeenCalledWith(expect.stringContaining("Animate"), asset);
  expect(close).toHaveBeenCalledOnce();
});
it("requires an editing instruction and keeps it when sending fails", async () => {
  const user = userEvent.setup(), send = vi.fn().mockRejectedValue(new Error("Connection unavailable")), close = vi.fn();
  render(<ResultFollowup draft={{ id: 1, asset, action: "edit" }} busy={false} onSend={send} onClose={close} />);
  expect(screen.getByRole("button", { name: "Send follow-up" })).toBeDisabled();
  await user.type(screen.getByRole("textbox"), "Make the light warmer");
  await user.click(screen.getByRole("button", { name: "Send follow-up" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Connection unavailable");
  expect(screen.getByRole("textbox")).toHaveValue("Edit this image: Make the light warmer");
  expect(close).not.toHaveBeenCalled();
});
