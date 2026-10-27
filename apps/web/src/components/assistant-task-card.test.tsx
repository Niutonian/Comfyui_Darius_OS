import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { AssistantTaskCard } from "./assistant-task-card";

it("acknowledges immediately without claiming the message is saved", () => {
  render(<AssistantTaskCard history={[]} elapsed={0} slow={false} saved={false} />);
  expect(screen.getByText("Got it — saving your message…")).toBeVisible();
});

it("shows real steps and failures without claiming a completed render", () => {
  render(<AssistantTaskCard history={[{ operation: "inspect_workflow", state: "complete" }, { operation: "validate_graph", state: "failed" }]} elapsed={9} slow={false} saved />);
  expect(screen.getByText("Validating the workflow · step failed")).toBeVisible();
  expect(screen.getByText("Task activity · 1 completed steps")).toBeVisible();
  expect(screen.queryByText("Render completed")).not.toBeInTheDocument();
});
