import { expect, it, vi } from "vitest";
import { readReplyStream, speechChunks } from "./reply-stream";

it("delivers deltas before completion and decodes split UTF-8", async () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const response = new Response(new ReadableStream({ start(value) { controller = value; } }));
  const delta = vi.fn();
  const result = readReplyStream(response, delta);
  const bytes = new TextEncoder().encode(JSON.stringify({ type: "delta", text: "café." }) + "\n");
  for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
  await vi.waitFor(() => expect(delta).toHaveBeenCalledWith("café."));
  controller.enqueue(new TextEncoder().encode(JSON.stringify({ type: "done", message: { content: "café.", id: "a" } }) + "\n"));
  await expect(result).resolves.toMatchObject({ content: "café.", id: "a" });
});

it("rejects incomplete streams and server errors", async () => {
  await expect(readReplyStream(new Response('{"type":"delta","text":"Partial"}\n'), vi.fn())).rejects.toThrow("incomplete");
  await expect(readReplyStream(new Response('{"type":"error","detail":"Task paused"}\n'), vi.fn())).rejects.toThrow("Task paused");
});

it("chunks complete sentences, preserves decimals and flushes unfinished tails", () => {
  expect(speechChunks("First sentence. A partial")).toEqual({ chunks: ["First sentence."], rest: "A partial" });
  expect(speechChunks("About 1.2 seconds! Last", true)).toEqual({ chunks: ["About 1.2 seconds!", "Last"], rest: "" });
  expect(speechChunks("About 1.")).toEqual({ chunks: [], rest: "About 1." });
  expect(speechChunks("x".repeat(500)).chunks.every((chunk) => chunk.length <= 240)).toBe(true);
});
