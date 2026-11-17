import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { canvasApi, type CanvasDocument } from "@/lib/canvas-api";
import { emptyCanvas } from "@/lib/canvas-document";
import { MOSS } from "@/lib/canvas-profile";
import { mossApi, prepareBoard, type MossBoard, type ProjectWorkspace } from "@/lib/moss-workspace";
import { clearWorkspaceSession } from "@/lib/workspace-session";
import { MossWorkspace } from "./moss-workspace";

vi.mock("@/lib/project-sync", () => ({ subscribeProjectRefresh: () => () => {} }));
vi.mock("@/lib/api-client", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/api-client")>(), request: vi.fn(async () => ({ derivatives: [] })) }));
vi.mock("@/lib/canvas-api", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/canvas-api")>(), canvasApi: { engine: vi.fn(), get: vi.fn(), generate: vi.fn(), save: vi.fn(), select: vi.fn(), start: vi.fn() } }));
vi.mock("@/lib/moss-workspace", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/moss-workspace")>(), mossApi: { get: vi.fn(), layout: vi.fn(), add: vi.fn(), save: vi.fn(), cancel: vi.fn() }, prepareBoard: vi.fn() }));
vi.mock("./canvas-workspace", () => ({ CanvasEditor: ({ onExit }: { onExit?: () => void }) => <div role="dialog" aria-label="Board editor stub"><button type="button" onClick={onExit}>Leave editor</button></div> }));

const board = (patch: Partial<MossBoard> = {}): MossBoard => ({ id: "board-a", projectId: "project-a", documentId: "doc-a", name: "Forest gate", kind: "moss-t2i", revision: 1, documentRevision: 1,
  settings: { adapterVersion: MOSS, seed: null, references: [] }, archived: false, artboard: { width: 1024, height: 1024, preset: "square" }, prompt: "A moss covered gate",
  regionCount: 2, layout: [], activeResult: null, previewAssetId: null, latest: null, jobs: [], newResult: false, ...patch });
const workspace = (boards: MossBoard[]): ProjectWorkspace => ({ projectId: "project-a", schemaVersion: 1, revision: 1, capacity: 1, queuePolicy: "single",
  placements: boards.map((b, order) => ({ boardId: b.id, x: order * 420, y: 0, displayWidth: 360, displayHeight: 450, order })), boards });
const doc = (): CanvasDocument => ({ id: "doc-a", projectId: "project-a", revision: 1, content: emptyCanvas(), activeGenerationId: null, updatedAt: "2026-11-17", generations: [] });

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><MossWorkspace projectId="project-a" assets={[]} /></QueryClientProvider>);
}

beforeEach(() => {
  clearWorkspaceSession();
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} unobserve() {} });
  vi.mocked(canvasApi.engine).mockResolvedValue({ adapterVersion: MOSS, presets: [] });
  vi.mocked(canvasApi.get).mockResolvedValue(doc());
  vi.mocked(mossApi.get).mockResolvedValue(workspace([board()]));
  vi.mocked(mossApi.layout).mockImplementation(async (_p, revision, placements) => ({ ...workspace([board()]), revision: revision + 1, placements }));
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("invites the first board when the project workspace is empty", async () => {
  vi.mocked(mossApi.get).mockResolvedValue(workspace([]));
  show();
  expect(await screen.findByRole("button", { name: "Add your first MOSS board" })).toBeInTheDocument();
});

it("shows each board as a card and selects it into the board panel", async () => {
  show();
  expect(await screen.findByRole("button", { name: "Open board Forest gate" })).toBeInTheDocument();
  fireEvent.click(screen.getByText("A moss covered gate"));
  const panel = await screen.findByRole("region", { name: "Selected board" });
  expect(panel).toHaveTextContent("Forest gate");
});

it("opens a board editor and returns to the workspace", async () => {
  vi.mocked(prepareBoard).mockResolvedValue({ boardId: "board-a", documentId: "doc-a", documentRevision: 1, boardRevision: 1, name: "Forest gate" });
  show();
  fireEvent.click(await screen.findByRole("button", { name: "Open board Forest gate" }));
  expect(await screen.findByRole("dialog", { name: "Board editor stub" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Leave editor" }));
  expect(await screen.findByRole("button", { name: "Open board Forest gate" })).toBeInTheDocument();
});

it("undoes a board position change from the keyboard", async () => {
  const { container } = show();
  fireEvent.click((await screen.findByText("A moss covered gate")));
  await screen.findByRole("region", { name: "Selected board" });
  const x = screen.getByRole("spinbutton", { name: "x" });
  fireEvent.change(x, { target: { value: "500" } });
  fireEvent.blur(x);
  const card = () => container.querySelector<HTMLElement>("[data-board-id='board-a']")!;
  await waitFor(() => expect(card().style.left).toBe("500px"));
  fireEvent.keyDown(screen.getByRole("region", { name: "MOSS board workspace" }), { key: "z", ctrlKey: true });
  await waitFor(() => expect(card().style.left).toBe("0px"));
});

it("prepares the board before submitting a generation", async () => {
  vi.mocked(prepareBoard).mockResolvedValue({ boardId: "board-a", documentId: "doc-a", documentRevision: 3, boardRevision: 1, name: "Forest gate", seed: 7, profileId: MOSS });
  vi.mocked(canvasApi.generate).mockResolvedValue({ id: "gen", jobId: "job", revision: 3, seed: 7, status: "queued", statusMessage: "Queued", error: null, assetIds: [], createdAt: "2026-11-17", provenance: {} } as never);
  show();
  fireEvent.click((await screen.findAllByRole("button", { name: "Generate" }))[0]);
  await waitFor(() => expect(canvasApi.generate).toHaveBeenCalled());
  const call = vi.mocked(canvasApi.generate).mock.calls[0];
  expect(call.slice(0, 2)).toEqual(["project-a", "doc-a"]);
  expect(call[2]).toBe(3);
  expect(call[4]).toBe(7);
});

it("keeps the canvas mounted underneath an open board", async () => {
  vi.mocked(prepareBoard).mockResolvedValue({ boardId: "board-a", documentId: "doc-a", documentRevision: 1, boardRevision: 1, name: "Forest gate" });
  const { container } = show();
  fireEvent.click(await screen.findByRole("button", { name: "Open board Forest gate" }));
  await screen.findByRole("dialog", { name: "Board editor stub" });
  expect(container.querySelector("[aria-label='MOSS board workspace']")).toHaveAttribute("aria-hidden", "true");
  fireEvent.click(screen.getByRole("button", { name: "Leave editor" }));
  await waitFor(() => expect(screen.getByRole("region", { name: "MOSS board workspace" })).not.toHaveAttribute("aria-hidden"));
});

it("contains a board whose settings cannot render instead of crashing the canvas", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(mossApi.get).mockResolvedValue(workspace([board({ kind: "image-recipe", settings: { adapterVersion: "qwen21-edit-v1", seed: null, references: [] } })]));
  show();
  fireEvent.click(await screen.findByText("A moss covered gate"));
  expect(await screen.findByText("This board's settings stopped working")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "MOSS board workspace" })).toBeInTheDocument();
  expect(screen.getByRole("toolbar", { name: "Canvas tools" })).toBeInTheDocument();
});
