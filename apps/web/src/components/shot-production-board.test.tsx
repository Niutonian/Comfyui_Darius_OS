import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import type { Asset, ShotBoardEntry } from "@/lib/types";
import { useDariusStore } from "@/lib/store";
import { ShotProductionBoard } from "./shot-production-board";

vi.mock("./asset-preview", () => ({ AssetPreview: ({ asset }: { asset: Asset }) => <span>Preview {asset.id}</span> }));
vi.mock("./production-structure", () => ({ ProductionStructure: () => <p>Production records</p> }));
afterEach(() => vi.restoreAllMocks());
const ref: Asset = { id: "ref", project_id: "p", kind: "image", role: "source", metadata: { display_name: "My reference" }, path: "", content_hash: "", mime_type: "image/png", width: null, height: null, duration: null, fps: null, sample_rate: null, parent_asset_ids: [], scene_id: null, shot_id: null, provider: "fixture", workflow_run_id: null, approval_state: "pending", created_at: "" };
const take = { ...ref, id: "take", kind: "video", metadata: { display_name: "My take" } } as Asset;
const row: ShotBoardEntry = { shot: { id: "s", scene_id: "scene", number: 1, description: "Arrival", shot_type: "wide", camera_motion: "", duration_target: 3, dialogue: "", status: "planned", selected_asset_id: null, created_at: "", updated_at: "" }, scene_title: "Station", scene_number: 1, references: [ref], takes: [take], jobs: [] };
function mount() {
  vi.spyOn(api, "shotBoard").mockResolvedValue([row]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><ShotProductionBoard projectId="p" assets={[ref, take, { ...ref, id: "foreign", project_id: "other", metadata: { display_name: "Foreign media" } }]} /></QueryClientProvider>);
}
it("chooses a take and excludes foreign project media", async () => {
  const user = userEvent.setup();
  const update = vi.spyOn(api, "updateShotProduction").mockResolvedValue(row.shot);
  mount();
  await screen.findByText("Arrival");
  expect(screen.queryByRole("option", { name: "Foreign media" })).not.toBeInTheDocument();
  await user.click(screen.getByText("Shot details & media"));
  await user.click(screen.getByText("Generations & takes · 1"));
  await user.click(screen.getByRole("button", { name: "Choose take" }));
  await waitFor(() => expect(update).toHaveBeenCalledWith("p", "s", { selected_asset_id: "take", status: "selected" }));
});
it("focuses the shot with saved references without rendering anything", async () => {
  const user = userEvent.setup();
  vi.spyOn(api, "assistantContext").mockResolvedValue({ notes: "Keep notes", character_id: null, scene_id: null, shot_id: null, reference_asset_ids: ["old"] });
  const save = vi.spyOn(api, "saveAssistantContext").mockResolvedValue({ notes: "Keep notes", character_id: null, scene_id: "scene", shot_id: "s", reference_asset_ids: ["ref"] });
  useDariusStore.setState({ activeProjectId: "p", referenceAssetIds: ["old"], view: "create" });
  mount();
  await user.click(await screen.findByRole("button", { name: "Work with Darius on this shot" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith("p", { notes: "Keep notes", character_id: null, scene_id: "scene", shot_id: "s", reference_asset_ids: ["ref"] }));
  await waitFor(() => expect(useDariusStore.getState().view).toBe("talk"));
  expect(useDariusStore.getState().referenceAssetIds).toEqual(["ref"]);
});
