import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import { publishProjectRefresh } from "@/lib/project-sync";
import { useDariusStore } from "@/lib/store";
import type { Asset, Character, Project, Scene, Shot } from "@/lib/types";
import { ConversationContext } from "./conversation-context";

vi.mock("./assistant-context", () => ({ AssistantContext: () => <p>Context editor</p> }));
const memory = { notes: "Use soft light", character_id: "tommy", scene_id: "forest", shot_id: "first", reference_asset_ids: ["pinned"] };
beforeEach(() => {
  useDariusStore.setState({ activeProjectId: "p", projects: [{ id: "p", name: "Forest film" } as Project], referenceAssetIds: [] });
  vi.spyOn(api, "assistantContext").mockResolvedValue(memory);
  vi.spyOn(api, "characters").mockResolvedValue([{ id: "tommy", name: "Tommy Nolan" } as Character]);
  vi.spyOn(api, "scenes").mockResolvedValue([{ id: "forest", number: 1, title: "Forest edge" } as Scene]);
  vi.spyOn(api, "shots").mockResolvedValue([{ id: "first", scene_id: "forest", number: 1 } as Shot]);
  vi.spyOn(api, "asset").mockImplementation(async id => ({ id, project_id: "p", kind: "image", metadata: { display_name: id === "pinned" ? "Forest reference" : "New portrait" } }) as unknown as Asset);
});
afterEach(() => vi.restoreAllMocks());

it("shows saved focus and readable references without opening settings", async () => {
  render(<ConversationContext projectId="p" busy={false} />);
  expect(await screen.findByText("Tommy Nolan")).toBeVisible();
  expect(screen.getByText("Scene 1 · Forest edge")).toBeVisible();
  expect(screen.getByText("Shot 1")).toBeVisible();
  expect(await screen.findByRole("img", { name: "Forest reference" })).toBeVisible();
  expect(screen.queryByText("Context editor")).not.toBeInTheDocument();
});

it("labels selected references separately and removes them without changing saved context", async () => {
  const user = userEvent.setup();
  useDariusStore.setState({ referenceAssetIds: ["selected"] });
  const save = vi.spyOn(api, "saveAssistantContext");
  render(<ConversationContext projectId="p" busy={false} />);
  expect(await screen.findByRole("img", { name: "New portrait" })).toBeVisible();
  expect(screen.getByText("1 selected reference")).toBeVisible();
  expect(screen.queryByRole("img", { name: "Forest reference" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Remove selected reference New portrait" }));
  expect(useDariusStore.getState().referenceAssetIds).toEqual([]);
  expect(save).not.toHaveBeenCalled();
  expect(await screen.findByText("1 pinned reference")).toBeVisible();
});

it("clears saved focus using fresh notes/defaults and does not render", async () => {
  const user = userEvent.setup();
  const fresh = { ...memory, notes: "Edited on laptop", workflow_preferences: { enabled: true, entries: [{ workflow_id: "base", purpose: "text-to-image", is_default: true }] } };
  vi.mocked(api.assistantContext).mockResolvedValue(fresh);
  const save = vi.spyOn(api, "saveAssistantContext").mockResolvedValue({ ...fresh, character_id: null, scene_id: null, shot_id: null, reference_asset_ids: [] });
  const reply = vi.spyOn(api, "assistantReplyStream");
  render(<ConversationContext projectId="p" busy={false} />);
  await screen.findByText("Tommy Nolan");
  await user.click(screen.getByRole("button", { name: "Change context" }));
  await user.click(screen.getByRole("button", { name: "Clear saved focus & references" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith("p", { ...fresh, character_id: null, scene_id: null, shot_id: null, reference_asset_ids: [] }));
  expect(reply).not.toHaveBeenCalled();
});

it("reflects remote context changes even while collapsed", async () => {
  render(<ConversationContext projectId="p" busy={false} />);
  await screen.findByText("Tommy Nolan");
  vi.mocked(api.assistantContext).mockResolvedValue({ ...memory, character_id: null, scene_id: null, shot_id: null, reference_asset_ids: [] });
  act(() => publishProjectRefresh({ projectId: "p", types: ["assistant.context_updated"], full: false }));
  expect(await screen.findByText("No saved focus · use the conversation")).toBeVisible();
  expect(screen.queryByText("Tommy Nolan")).not.toBeInTheDocument();
});

it("does not display media returned from a different project", async () => {
  vi.mocked(api.asset).mockResolvedValue({ id: "pinned", project_id: "other", kind: "image", metadata: { display_name: "Private image" } } as unknown as Asset);
  render(<ConversationContext projectId="p" busy={false} />);
  await screen.findByText("Tommy Nolan");
  expect(screen.queryByRole("img", { name: "Private image" })).not.toBeInTheDocument();
});
