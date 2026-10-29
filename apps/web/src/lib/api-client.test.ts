import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api-client";

afterEach(() => vi.restoreAllMocks());

describe("api client", () => {
  it("times out stalled workflow discovery and aborts the request", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
      const result = expect(api.workflows()).rejects.toMatchObject({ status: 408, message: expect.stringContaining("retry") });
      await vi.advanceTimersByTimeAsync(20_000);
      await result;
      expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
    } finally { vi.useRealTimers(); }
  });

  it("times out a stalled assistant reply and aborts the request", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
      const result = expect(api.assistantReply("conversation-1", "message-1")).rejects.toMatchObject({ status: 408, message: expect.stringContaining("retry") });
      await vi.advanceTimersByTimeAsync(300_000);
      await result;
      expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
    } finally { vi.useRealTimers(); }
  });

  it("creates a project through the versioned API", async () => {
    const project = { id: "p1", name: "Night Train", description: "", created_at: "2026-01-01", updated_at: "2026-01-01" };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(project), { status: 201, headers: { "Content-Type": "application/json" } }));

    await expect(api.createProject({ name: "Night Train", description: "" })).resolves.toEqual(project);
    expect(fetchMock).toHaveBeenCalledWith("/api/darius/api/v1/projects", expect.objectContaining({ method: "POST", body: JSON.stringify({ name: "Night Train", description: "" }) }));
  });

  it("normalizes FastAPI detail errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "approval required" }), { status: 409, headers: { "Content-Type": "application/json" } }));
    await expect(api.createRequest("p1", { workflow_id: "w1", request_text: "test", inputs: {}, approved: false })).rejects.toMatchObject({ status: 409, message: "approval required" });
  });

  it("renders structured validation errors with field names instead of object strings", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: [
      { type: "extra_forbidden", loc: ["body", "documentId"], msg: "Extra inputs are not permitted", input: "private-document-value" },
      { type: "extra_forbidden", loc: ["body", "name"], msg: "Extra inputs are not permitted", input: "private-project-name" },
      { loc: ["body", "regions", 2, "width"], msg: "Input should be greater than 0" },
    ] }), { status: 422 }));
    await expect(api.health()).rejects.toMatchObject({ status: 422,
      message: "documentId: Extra inputs are not permitted; name: Extra inputs are not permitted; regions.2.width: Input should be greater than 0",
      detail: "documentId: Extra inputs are not permitted; name: Extra inputs are not permitted; regions.2.width: Input should be greater than 0" });
  });

  it("unwraps nested error details without exposing rejected input data", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: { error: { message: "The selected workflow is unavailable", input: "private-value" } } }), { status: 409 }));
    await expect(api.health()).rejects.toMatchObject({ status: 409, message: "The selected workflow is unavailable" });
  });

  it("reports backend unavailability clearly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("connection refused"));
    await expect(api.health()).rejects.toMatchObject({ status: 0, message: expect.stringContaining("offline") });
  });

  it("uploads project-associated immutable media as multipart form data", async () => {
    const uploaded = { id: "asset-1", project_id: "p1", kind: "image" };
    let sentBody: Document | XMLHttpRequestBodyInit | null = null;
    class FakeXMLHttpRequest {
      upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
      response = uploaded;
      responseType: XMLHttpRequestResponseType = "";
      status = 201;
      statusText = "Created";
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onabort: (() => void) | null = null;
      open() {}
      abort() { this.onabort?.(); }
      send(body: Document | XMLHttpRequestBodyInit | null) {
        sentBody = body;
        this.upload.onprogress?.({ lengthComputable: true, loaded: 10, total: 10 } as ProgressEvent);
        this.onload?.();
      }
    }
    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
    const progress = vi.fn();
    await expect(api.uploadAssetWithProgress(new File(["image"], "reference.png", { type: "image/png" }), { project_id: "p1", role: "reference" }, { onProgress: progress })).resolves.toEqual(uploaded);
    expect(sentBody).toBeInstanceOf(FormData);
    const form = sentBody as unknown as FormData;
    expect(form.get("project_id")).toBe("p1");
    expect(form.get("role")).toBe("reference");
    expect(progress).toHaveBeenLastCalledWith({ loaded: 5, total: 5, percent: 100 });
    vi.unstubAllGlobals();
  });
});


it.each([{ name: "chat list", load: () => api.conversations("p") }, { name: "history", load: () => api.messages("c") }])("allows a slow $name read to finish after 20 seconds without replaying a message", async ({ load }) => {
 vi.useFakeTimers();
 try {
  let resolve!: (value: Response) => void;
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>(done => { resolve = done; }));
  let finished = false;
  const pending = load().then(value => { finished = true; return value; });
  await vi.advanceTimersByTimeAsync(25_000);
  expect(finished).toBe(false); expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(false);
  resolve(new Response("[]")); await expect(pending).resolves.toEqual([]);
  expect(fetch).toHaveBeenCalledOnce(); expect(fetch.mock.calls[0][1]?.method).toBeUndefined();
 } finally { vi.useRealTimers(); }
});

it("bounds stalled history reads and explains saved-history recovery", async () => {
 vi.useFakeTimers();
 try {
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
  const pending = expect(api.messages("c")).rejects.toMatchObject({ status: 408, message: expect.stringContaining("messages are still saved") });
  await vi.advanceTimersByTimeAsync(45_000); await pending;
  expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);
 } finally { vi.useRealTimers(); }
});
