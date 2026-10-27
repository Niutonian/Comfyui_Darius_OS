import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { usePipecatVoiceConversation } from "./use-pipecat-voice-conversation";
import { useVoicePreferences } from "./voice-preferences";

class Socket {
  static OPEN = 1; static latest: Socket;
  readyState = 1; bufferedAmount = 0;
  onmessage?: (event: { data: string }) => void;
  onclose?: () => void;
  send = vi.fn(); close = vi.fn();
  constructor() { Socket.latest = this; setTimeout(() => this.emit({ type: "ready", backend: "pipecat" }), 0); }
  emit(value: object) { this.onmessage?.({ data: JSON.stringify(value) }); }
}
const sources: { buffer: unknown; connect: ReturnType<typeof vi.fn>; start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn>; onended: (() => void) | null }[] = [];
class Context {
  currentTime = 0; destination = {};
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
  resume = vi.fn().mockResolvedValue(undefined); close = vi.fn().mockResolvedValue(undefined);
  createMediaStreamSource = () => ({ connect: vi.fn() });
  createGain = () => ({ gain: { value: 0 }, connect: vi.fn() });
  createBuffer = (_channels: number, samples: number, rate: number) => ({ duration: samples / rate, getChannelData: () => new Float32Array(samples) });
  createBufferSource = () => { const source = { buffer: null, connect: vi.fn(), start: vi.fn(), stop: vi.fn(), onended: null }; sources.push(source); return source; };
}
class Worklet {
  static latest: Worklet;
  port: { onmessage?: (event: { data: ArrayBuffer }) => void } = {};
  connect = vi.fn();
  constructor() { Worklet.latest = this; }
}
beforeEach(() => {
  sources.length = 0;
  vi.stubGlobal("WebSocket", Socket); vi.stubGlobal("AudioContext", Context); vi.stubGlobal("AudioWorkletNode", Worklet);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ready: true }) }));
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn(), onended: null }] }) } });
  useVoicePreferences.setState({ spokenReplies: true, silenceSeconds: 1.2, pipecatVoice: "af_heart" });
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
function commands() { return Socket.latest.send.mock.calls.flatMap(([value]) => typeof value === "string" ? [JSON.parse(value)] : []); }
const packet = (id: string) => ({ type: "audio", turn_id: id, sample_rate: 24000, pcm: btoa("\0".repeat(4800)) });

it("keeps microphone capture active while a Darius request is running", async () => {
  let finish!: (text: string) => void;
  const callback = vi.fn(() => new Promise<string>((resolve) => { finish = resolve; }));
  const { result } = renderHook(() => usePipecatVoiceConversation(callback));
  act(() => { void result.current.start(); });
  await waitFor(() => expect(result.current.phase).toBe("listening"));
  act(() => Socket.latest.emit({ type: "final", turn_id: "a", text: "Imagine a forest" }));
  expect(callback).toHaveBeenCalledOnce();
  const pcm = new ArrayBuffer(2048);
  act(() => Worklet.latest.port.onmessage?.({ data: pcm }));
  expect(Socket.latest.send).toHaveBeenCalledWith(pcm);
  expect(commands().some((command) => command.mode === "paused")).toBe(false);
  await act(async () => finish("A quiet forest."));
});

it("plays streamed PCM before the full reply and finishes only after playback", async () => {
  let finish!: (text: string) => void; let delta!: (text: string) => void;
  const { result } = renderHook(() => usePipecatVoiceConversation((_text, onDelta) => { delta = onDelta!; return new Promise<string>((resolve) => { finish = resolve; }); }));
  act(() => { void result.current.start(); });
  await waitFor(() => expect(result.current.phase).toBe("listening"));
  act(() => Socket.latest.emit({ type: "final", turn_id: "a", text: "Hello" }));
  act(() => delta("A first sentence. More"));
  expect(commands()).toContainEqual({ type: "reply_chunk", turn_id: "a", text: "A first sentence." });
  act(() => Socket.latest.emit(packet("a")));
  expect(result.current.phase).toBe("speaking"); expect(sources[0].start).toHaveBeenCalled();
  await act(async () => finish("A first sentence. More"));
  act(() => Socket.latest.emit({ type: "audio_done", turn_id: "a" }));
  expect(result.current.phase).toBe("speaking");
  act(() => sources[0].onended?.());
  expect(result.current.phase).toBe("listening");
});

it("interrupts audio without cancelling or replaying the original task and holds the follow-up", async () => {
  let finish!: (text: string) => void;
  const callback = vi.fn().mockImplementationOnce(() => new Promise<string>((resolve) => { finish = resolve; })).mockResolvedValue("A red boat.");
  const { result } = renderHook(() => usePipecatVoiceConversation(callback));
  act(() => { void result.current.start(); });
  await waitFor(() => expect(result.current.phase).toBe("listening"));
  act(() => Socket.latest.emit({ type: "final", turn_id: "a", text: "Make a boat" }));
  act(() => Socket.latest.emit(packet("a")));
  act(() => Socket.latest.emit({ type: "speech_started" }));
  expect(sources[0].stop).toHaveBeenCalledOnce();
  act(() => Socket.latest.emit({ type: "final", turn_id: "b", text: "Make the next one red" }));
  expect(result.current.waitingForReply).toBe(true); expect(callback).toHaveBeenCalledOnce();
  await act(async () => finish("The first job is queued."));
  await waitFor(() => expect(callback).toHaveBeenCalledTimes(2));
  expect(callback).toHaveBeenLastCalledWith("Make the next one red", expect.any(Function));
  expect(commands().filter((command) => command.turn_id === "a")).toHaveLength(0);
  act(() => Socket.latest.emit(packet("a")));
  expect(sources).toHaveLength(1);
});

it("reports an unavailable sidecar without silently switching speech engines", async () => {
  vi.mocked(fetch).mockResolvedValueOnce({ json: async () => ({ ready: false, error: "Models are warming up" }) } as Response);
  const callback = vi.fn();
  const { result } = renderHook(() => usePipecatVoiceConversation(callback));
  await act(async () => result.current.start());
  expect(result.current.phase).toBe("off"); expect(result.current.error).toContain("warming up");
  expect(callback).not.toHaveBeenCalled();
});

it("releases output, microphone and socket when ending the session", async () => {
  const { result } = renderHook(() => usePipecatVoiceConversation(async () => "Ready."));
  act(() => { void result.current.start(); });
  await waitFor(() => expect(result.current.phase).toBe("listening"));
  const socket = Socket.latest;
  act(() => result.current.stop());
  expect(socket.close).toHaveBeenCalledOnce(); expect(result.current.phase).toBe("off");
  act(() => socket.emit({ type: "final", turn_id: "old", text: "Stale input" }));
  expect(result.current.phase).toBe("off");
});

it("treats a standalone spoken stop as a voice interruption, not permission to cancel a job", async () => {
  const callback = vi.fn();
  const { result } = renderHook(() => usePipecatVoiceConversation(callback));
  act(() => { void result.current.start(); });
  await waitFor(() => expect(result.current.phase).toBe("listening"));
  act(() => Socket.latest.emit({ type: "final", turn_id: "stop", text: "Darius, stop." }));
  expect(callback).not.toHaveBeenCalled();
  expect(result.current.phase).toBe("listening");
  expect(commands()).toContainEqual({ type: "interrupt" });
});
