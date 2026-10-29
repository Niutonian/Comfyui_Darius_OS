import { afterEach, expect, it, vi } from "vitest";
import { canvasApi } from "./canvas-api";
import { loadCanvasIntent } from "./canvas-intent";
import { subscribeBoardSetup } from "./board-setup";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); sessionStorage.clear(); });

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


it("recovers a committed receipt after the submission response is lost", async () => {
  const receipt = { id: "recovered", jobId: "one-job", status: "queued" };
  const fetch = vi.spyOn(globalThis, "fetch")
    .mockRejectedValueOnce(new TypeError("Connection lost after commit"))
    .mockResolvedValueOnce(new Response(JSON.stringify(receipt)));
  const checking = vi.fn();
  await expect(canvasApi.generate("p", "d", 1, "original-key", 42, undefined, checking)).resolves.toEqual(receipt);
  expect(fetch.mock.calls.map(call => call[1]?.method ?? "GET")).toEqual(["POST", "GET"]);
  expect(String(fetch.mock.calls[1][0])).toContain("/requests/original-key");
  expect(checking).toHaveBeenCalledOnce();
  expect(loadCanvasIntent("p", "d")).toBeUndefined();
});

it("retains an uncertain request through reload and reconciles before resubmitting", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "busy" }), { status: 503 }));
  await expect(canvasApi.generate("p", "d", 7, "retry-key", "18446744073709551615")).rejects.toThrow("request is saved");
  const saved = loadCanvasIntent("p", "d")!;
  expect(saved).toMatchObject({ key: "retry-key", revision: 7, seed: "18446744073709551615" });
  fetch.mockReset().mockResolvedValueOnce(new Response(JSON.stringify({ id: "existing", status: "completed" })));
  await expect(canvasApi.generate("p", "d", saved.revision, saved.key, saved.seed)).resolves.toMatchObject({ id: "existing" });
  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0][1]?.method).toBeUndefined();
});

it("bounds submission at 45 seconds and preserves its key after a timeout", async () => {
  vi.useFakeTimers();
  const fetch = vi.spyOn(globalThis, "fetch")
    .mockImplementationOnce(() => new Promise(() => {}))
    .mockResolvedValueOnce(new Response("null"));
  const pending = expect(canvasApi.generate("p", "d", 1, "timeout-key", 42)).rejects.toMatchObject({ status: 408 });
  await vi.advanceTimersByTimeAsync(45_000);
  await pending;
  expect(loadCanvasIntent("p", "d")?.key).toBe("timeout-key");
  expect(fetch).toHaveBeenCalledTimes(2);
});

it.each([408, 429, 503])("preserves retry identity for HTTP %s", async status => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "retry later" }), { status }));
  await expect(canvasApi.generate("p", "d", 1, "retained-key", 42)).rejects.toMatchObject({ status });
  expect(loadCanvasIntent("p", "d")?.key).toBe("retained-key");
});

it("drops a definitively rejected request so corrected input can be submitted", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Invalid input" }), { status: 422 }));
  await expect(canvasApi.generate("p", "d", 1, "invalid-key", 42)).rejects.toMatchObject({ status: 422 });
  expect(loadCanvasIntent("p", "d")).toBeUndefined();
  expect(fetch).toHaveBeenCalledOnce();
});
