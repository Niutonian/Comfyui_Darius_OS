import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ConversationRow } from "./conversation-row";

const thread = { id: "c", project_id: "p", title: "New chat", created_at: "", updated_at: "" };
it("renames inline and requires explicit deletion confirmation", async () => {
  const user = userEvent.setup(), rename = vi.fn().mockResolvedValue(undefined), remove = vi.fn().mockResolvedValue(undefined);
  render(<ConversationRow thread={thread} active disabled={false} onOpen={vi.fn()} onRename={rename} onDelete={remove} onError={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Rename chat New chat" }));
  await user.clear(screen.getByLabelText("Chat name"));
  expect(screen.getByRole("button", { name: "Save name" })).toBeDisabled();
  await user.type(screen.getByLabelText("Chat name"), "  My film  ");
  await user.click(screen.getByRole("button", { name: "Save name" }));
  await waitFor(() => expect(rename).toHaveBeenCalledWith("My film"));
  await user.click(screen.getByRole("button", { name: "Delete chat New chat" }));
  expect(remove).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(remove).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Delete chat New chat" }));
  await user.click(screen.getByRole("button", { name: "Confirm delete" }));
  await waitFor(() => expect(remove).toHaveBeenCalledTimes(1));
});
