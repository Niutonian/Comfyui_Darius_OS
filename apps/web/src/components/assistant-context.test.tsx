import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import { publishProjectRefresh } from "@/lib/project-sync";
import { AssistantContext } from "./assistant-context";

vi.mock("./assistant-references", () => ({ ConversationImages: () => null }));
afterEach(() => vi.restoreAllMocks());

it("updates clean context but keeps an unsaved note when another device changes it", async () => {
  const user = userEvent.setup();
  const memory = { notes: "Saved note", reference_asset_ids: [], character_id: null, scene_id: null, shot_id: null };
  const load = vi.spyOn(api, "assistantContext").mockResolvedValue(memory);
  vi.spyOn(api, "characters").mockResolvedValue([]);
  vi.spyOn(api, "scenes").mockResolvedValue([]);
  render(<AssistantContext projectId="p" busy={false} />);
  await user.click(screen.getByText("Project context"));
  expect(await screen.findByDisplayValue("Saved note")).toBeInTheDocument();
  load.mockResolvedValue({ ...memory, notes: "Updated on laptop" });
  act(() => publishProjectRefresh({ projectId: "p", full: false, types: ["assistant.context_updated"] }));
  const notes = await screen.findByDisplayValue("Updated on laptop");
  await user.clear(notes); await user.type(notes, "My unsaved phone note");
  load.mockResolvedValue({ ...memory, notes: "Updated elsewhere again" });
  act(() => publishProjectRefresh({ projectId: "p", full: false, types: ["assistant.context_updated"] }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Your unsaved edits are kept"));
  expect(notes).toHaveValue("My unsaved phone note");
});
