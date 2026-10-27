import { afterEach, expect, it, vi } from "vitest";
import { canvasApi } from "./canvas-api";
import { loadCanvasIntent } from "./canvas-intent";
import { subscribeBoardSetup } from "./board-setup";

afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

it("prepares missing dependencies and resumes only the exact saved generation request", async () => {
  const fetch = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Board setup required: Missing model" }), { status: 422 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: "generated-after-setup", status: "queued" }), { status: 200 }));
  const stop = subscribeBoardSetup(value => { expect(value.profile).toBe("fibo-dev-v1"); value.resolve(); });
  try {
    const value = await canvasApi.generate("p", "d", 7, "same-key", "18446744073709551615", { boardId: "board", boardRevision: 3, profileId: "fibo-dev-v1" });
    expect(value.id).toBe("generated-after-setup");
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[0][1]!.body).toEqual(fetch.mock.calls[1][1]!.body);
  } finally { stop(); }
});

it("does not retry a render when board setup is closed", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Board setup required: Missing node" }), { status: 422 }));
  const stop = subscribeBoardSetup(value => value.reject(new Error("Setup closed")));
  try { await expect(canvasApi.generate("p", "d", 1, "key", 42)).rejects.toThrow("Setup closed"); expect(fetch).toHaveBeenCalledTimes(1); }
  finally { stop(); }
});

it("sends only generation API fields when the overview passes its full saved intent", async () => {
  const receipt = { id: "generation-a", status: "queued" };
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(receipt), { status: 200 }));
  const overviewIntent = { boardId: "board-a", boardRevision: 3, profileId: "moss-bboxes-v1",
    documentId: "document-a", documentRevision: 36, name: "Alien", key: "overview-retry-key",
    revision: 999, seed: "999", approved: false };
  await expect(canvasApi.generate("project-a", "document-a", 36, "overview-retry-key", 42, overviewIntent)).resolves.toEqual(receipt);
  const payload = JSON.parse(fetch.mock.calls[0][1]!.body as string);
  expect(payload).toEqual({ revision: 36, idempotencyKey: "overview-retry-key", seed: 42, approved: true,
    boardId: "board-a", boardRevision: 3, profileId: "moss-bboxes-v1" });
  expect(loadCanvasIntent("project-a", "document-a")).toBeUndefined();
});

it("keeps promotion fields and exact large seeds while retaining only transport identity on an uncertain reply", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Connection lost"));
  const intent = { boardId: "board-a", boardRevision: 9, profileId: "fibo-dev-v1", promotedFromGenerationId: "preview-a",
    documentId: "document-a", name: "Alien", documentRevision: 99, key: "unexpected-extra-key" };
  await expect(canvasApi.generate("project-a", "document-a", 2, "promotion-retry-key", "18446744073709551615", intent)).rejects.toMatchObject({ status: 0 });
  expect(loadCanvasIntent("project-a", "document-a:promote:preview-a")).toEqual({ revision: 2, key: "promotion-retry-key",
    seed: "18446744073709551615", documentId: "document-a", boardId: "board-a", boardRevision: 9,
    profileId: "fibo-dev-v1", promotedFromGenerationId: "preview-a" });
  expect(loadCanvasIntent("project-a", "document-a")).toBeUndefined();
});
