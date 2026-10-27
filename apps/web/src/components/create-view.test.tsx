import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CreateView, groupLibrary } from "./create-view";
import { useDariusStore } from "@/lib/store";
import type { Asset, Character, Scene } from "@/lib/types";

const assets = [
  { id: "a1", kind: "image", role: "generation", scene_id: "forest", metadata: {} },
  { id: "a2", kind: "video", role: "source", scene_id: null, metadata: {} },
  { id: "a3", kind: "image", role: "reference", scene_id: "forest", metadata: {} },
] as unknown as Asset[];
const characters = [{ id: "mara", name: "Mara", approved_reference_asset_ids: ["a3"] }] as Character[];
const scenes = [{ id: "forest", title: "Forest" }] as Scene[];

vi.mock("@/lib/queries", async original => ({ ...await original<typeof import("@/lib/queries")>(), useCharacters: () => ({ data: characters }), useScenes: () => ({ data: scenes }) }));
vi.mock("./local-render-setting", () => ({ LocalRenderSetting: () => null }));
vi.mock("./asset-preview", () => ({ AssetPreview: ({ asset, navigationAssets }: { asset: Asset; navigationAssets?: Asset[] }) => <span data-testid="library-preview" data-navigation={navigationAssets?.map(a => a.id).join(",")}>{asset.id}</span> }));

function media(id: string, role: string, kind = "image"): Asset {
  return { id, project_id: "library-project", kind, role, path: `/mock/${id}`, content_hash: "a".repeat(64), mime_type: kind === "image" ? "image/png" : "video/mp4", width: 2048, height: 2048,
    duration: null, fps: null, sample_rate: null, parent_asset_ids: [], scene_id: null, shot_id: null, provider: "local-comfyui", workflow_run_id: null, approval_state: "pending", metadata: { display_name: id }, created_at: "2026-10-24" };
}
beforeEach(() => { useDariusStore.setState({ activeProjectId: "library-project" }); window.history.replaceState({}, "", "/"); });

it("keeps only original media in library cards, counts, navigation, role stacks and search", () => {
  const originals = [media("Full-size render", "generation"), media("Original video", "generation", "video")];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><CreateView assets={[...originals, media("Render thumbnail", "derivative"), media("Video proxy", "derivative", "video")]} isLoading={false} hasError={false} /></QueryClientProvider>);
  expect(screen.getByRole("button", { name: "Inspect Full size render" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Inspect Original video" })).toBeVisible();
  expect(screen.queryByText("Render thumbnail")).toBeNull();
  expect(screen.queryByText("Video proxy")).toBeNull();
  expect(within(screen.getByRole("button", { name: /^All media/ })).getByText("2")).toBeVisible();
  expect(within(screen.getByRole("button", { name: /^Images/ })).getByText("1")).toBeVisible();
  for (const preview of screen.getAllByTestId("library-preview")) expect(preview).toHaveAttribute("data-navigation", "Full-size render,Original video");
  fireEvent.click(screen.getByRole("button", { name: /Stacks/ }));
  fireEvent.change(screen.getByRole("combobox", { name: "Stack by" }), { target: { value: "role" } });
  expect(screen.queryByText("Derivative")).toBeNull();
  fireEvent.change(screen.getByRole("textbox", { name: "Search assets" }), { target: { value: "thumbnail" } });
  expect(screen.getByText("No matching assets")).toBeVisible();
});

it("treats a project with only cached previews as an empty library", () => {
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><CreateView assets={[media("Cached thumbnail", "derivative")]} isLoading={false} hasError={false} /></QueryClientProvider>);
  expect(screen.getByText("Your canvas is ready")).toBeVisible();
  expect(screen.queryByText("Cached thumbnail")).toBeNull();
});

describe("Library stacks", () => {
  it("groups by kind, scene, and character ownership", () => {
    expect(groupLibrary(assets, characters, scenes, "kind").map((group) => [group.label, group.items.length])).toEqual([["Image", 2], ["Video", 1]]);
    expect(groupLibrary(assets, characters, scenes, "scene").map((group) => group.label).sort()).toEqual(["Forest", "Unplaced"]);
    const byCharacter = groupLibrary(assets, characters, scenes, "character");
    expect(byCharacter.find((group) => group.label === "Mara")?.items.map((item) => item.id)).toEqual(["a3"]);
    expect(byCharacter.find((group) => group.label === "Unassigned")?.items).toHaveLength(2);
  });
});
