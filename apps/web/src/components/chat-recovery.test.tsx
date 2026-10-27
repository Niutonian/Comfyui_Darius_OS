import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { Message } from "@/lib/types";
import { ChatRecovery } from "./chat-recovery";

it("offers a deliberate saved-request retry rather than automatic generation", () => {
  const message = { metadata: { recovery: { action: "retry", can_retry: true } } } as unknown as Message;
  const retry = vi.fn();
  const view = render(<ChatRecovery message={message} busy={false} onRetry={retry} />);
  expect(retry).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Retry saved request" }));
  expect(retry).toHaveBeenCalledWith(message);
  view.rerender(<ChatRecovery message={message} busy onRetry={retry} />);
  expect(screen.getByRole("button", { name: "Retry saved request" })).toBeDisabled();
});

it("asks for clarification without offering a blind retry", () => {
  const message = { metadata: { recovery: { action: "clarify", can_retry: false } } } as unknown as Message;
  render(<ChatRecovery message={message} busy={false} onRetry={vi.fn()} />);
  expect(screen.getByText(/Reply in chat with the missing detail/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Retry saved request" })).not.toBeInTheDocument();
});
