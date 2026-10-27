import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLocalVoiceConversation } from "./use-local-voice-conversation";
import { useVoicePreferences } from "./voice-preferences";

class Socket {
  static OPEN = 1;
  static latest: Socket;
  readyState = 1;
  bufferedAmount = 0;
  onmessage?: (event: { data: string }) => void;
  onclose?: () => void;
  send = vi.fn(); close = vi.fn();
  constructor() { Socket.latest = this; setTimeout(() => this.emit({ type: "ready" }), 0); }
  emit(data: object) { this.onmessage?.({ data: JSON.stringify(data) }); }
}
const track = { stop: vi.fn(), onended: null };
const player = { buffer: null, connect: vi.fn(), start: vi.fn(), stop: vi.fn(), onended: null as (() => void) | null };
class Context {
  destination = {};
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
  resume = vi.fn().mockResolvedValue(undefined);
  close = vi.fn().mockResolvedValue(undefined);
  decodeAudioData = vi.fn().mockResolvedValue({});
  createBufferSource = () => player;
  createMediaStreamSource = () => ({ connect: vi.fn() });
  createGain = () => ({ gain: { value: 0 }, connect: vi.fn() });
}
const fetchMock = vi.fn();
beforeEach(() => {
  useVoicePreferences.setState({ spokenReplies: true, silenceSeconds: 1.2, voiceDescription: "", speechEngine: "omnivoice" });
  vi.clearAllMocks();
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("AudioContext", Context);
  vi.stubGlobal("AudioWorkletNode", class { port = { onmessage: null }; connect = vi.fn(); });
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation(async (url: string) => url.endsWith("/health") ? { json: async () => ({ wake_ready: true, tts_ready: true, transcription_ready: true }) } : { ok: true, arrayBuffer: async () => new ArrayBuffer(8) });
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) } });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); Reflect.deleteProperty(window, "speechSynthesis"); });

describe("local voice", () => {
  it("prefetches one next chunk during playback without overlapping speech", async () => {
    const { result } = renderHook(() => useLocalVoiceConversation(vi.fn().mockResolvedValue("First sentence. Second sentence. Third sentence.")));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    act(() => Socket.latest.emit({ type: "final", text: "hello" }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/tts"))).toHaveLength(2));
    expect(player.start).toHaveBeenCalledTimes(1);
    act(() => player.onended?.());
    await waitFor(() => expect(player.start).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/tts"))).toHaveLength(3));
    act(() => player.onended?.());
    await waitFor(() => expect(player.start).toHaveBeenCalledTimes(3));
    act(() => player.onended?.());
    expect(result.current.phase).toBe("listening");
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("stops prefetched audio on a voice interruption and ignores stale epochs", async () => {
    const { result } = renderHook(() => useLocalVoiceConversation(vi.fn().mockResolvedValue("First. Second. Third.")));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    act(() => Socket.latest.emit({ type: "final", text: "hello" }));
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    const epoch = JSON.parse(Socket.latest.send.mock.calls.at(-1)![0]).epoch;
    act(() => Socket.latest.emit({ type: "interrupt", epoch: epoch - 1 }));
    expect(result.current.phase).toBe("speaking");
    act(() => Socket.latest.emit({ type: "interrupt", epoch }));
    expect(result.current.phase).toBe("listening");
    expect(player.stop).toHaveBeenCalled();
    await act(async () => player.onended?.());
    expect(player.start).toHaveBeenCalledTimes(1);
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("holds an interrupted follow-up until the current model reply settles", async () => {
    let finish!: (text: string) => void;
    let delta!: (text: string) => void;
    const turn = vi.fn((_text: string, onDelta?: (text: string) => void) => {
      delta = onDelta!;
      return new Promise<string>((resolve) => { finish = resolve; });
    }).mockResolvedValueOnce("Initial");
    // The second model turn remains in flight while the user interrupts it.
    const { result, rerender } = renderHook(({ blocked }) => useLocalVoiceConversation(turn, blocked), { initialProps: { blocked: false } });
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    act(() => Socket.latest.emit({ type: "final", text: "first" }));
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    act(() => player.onended?.());
    act(() => Socket.latest.emit({ type: "final", text: "second" }));
    rerender({ blocked: true });
    act(() => delta("In progress. More"));
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    act(() => Socket.latest.emit({ type: "interrupt" }));
    act(() => Socket.latest.emit({ type: "final", text: "My follow-up" }));
    expect(result.current.waitingForReply).toBe(true);
    expect(result.current.transcript).toBe("My follow-up");
    expect(turn).toHaveBeenCalledTimes(2);
    turn.mockResolvedValueOnce("Follow-up answer");
    await act(async () => finish("In progress. More"));
    rerender({ blocked: false });
    await waitFor(() => expect(turn).toHaveBeenCalledTimes(3));
    expect(turn.mock.calls[2][0]).toBe("My follow-up");
    expect(result.current.waitingForReply).toBe(false);
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    act(() => player.onended?.());
    expect(result.current.phase).toBe("listening");
  });

  it("ending voice discards a held follow-up", async () => {
    const turn = vi.fn().mockResolvedValue("Reply");
    const { result, rerender } = renderHook(({ blocked }) => useLocalVoiceConversation(turn, blocked), { initialProps: { blocked: true } });
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    act(() => Socket.latest.emit({ type: "final", text: "Follow-up" }));
    expect(result.current.waitingForReply).toBe(true);
    act(() => result.current.endConversation());
    rerender({ blocked: false });
    expect(turn).not.toHaveBeenCalled();
    expect(result.current.phase).toBe("off");
  });

  it("speaks the first sentence before completion, keeps capture paused, and does not repeat streamed speech", async () => {
    let finish!: (text: string) => void;
    let delta!: (text: string) => void;
    const turn = vi.fn((_text: string, onDelta?: (text: string) => void) => {
      delta = onDelta!;
      return new Promise<string>((resolve) => { finish = resolve; });
    });
    const { result } = renderHook(() => useLocalVoiceConversation(turn));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    act(() => Socket.latest.emit({ type: "final", text: "Hello" }));
    act(() => delta("First sentence. More"));
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    expect(JSON.parse(fetchMock.mock.calls.filter(([url]) => url.endsWith("/tts"))[0][1].body).text).toBe("First sentence.");
    act(() => player.onended?.());
    expect(result.current.phase).toBe("thinking");
    expect(JSON.parse(Socket.latest.send.mock.calls.at(-1)![0]).mode).toBe("interrupt");
    await act(async () => { delta(" arrives."); finish("First sentence. More arrives."); });
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/tts")).map(([, options]) => JSON.parse(options.body).text)).toEqual(["First sentence.", "More arrives."]);
    act(() => player.onended?.());
    expect(result.current.phase).toBe("listening");
  });

  it("discards queued and late streamed speech when stopped", async () => {
    let finish!: (text: string) => void;
    let delta!: (text: string) => void;
    const { result } = renderHook(() => useLocalVoiceConversation((_text, onDelta) => {
      delta = onDelta!;
      return new Promise<string>((resolve) => { finish = resolve; });
    }));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    act(() => Socket.latest.emit({ type: "final", text: "Hello" }));
    act(() => delta("First. Second."));
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    act(() => result.current.stop());
    await act(async () => { delta(" Late."); finish("First. Second. Late."); player.onended?.(); });
    expect(result.current.phase).toBe("off");
    expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/tts"))).toHaveLength(1);
  });

  it("uses the Windows voice audio path across three consecutive turns", async () => {
    useVoicePreferences.setState({ speechEngine: "fast", deviceVoiceURI: "Microsoft Zira Desktop" });
    const turn = vi.fn().mockResolvedValue("A quick answer");
    const { result } = renderHook(() => useLocalVoiceConversation(turn));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    const ws = Socket.latest;
    for (const text of ["first", "second", "third"]) {
      act(() => ws.emit({ type: "final", text }));
      await waitFor(() => expect(result.current.phase).toBe("speaking"));
      const call = fetchMock.mock.calls.filter(([url]) => url.endsWith("/tts")).at(-1)!;
      expect(JSON.parse(call[1].body)).toMatchObject({ engine: "system", voice: "Microsoft Zira Desktop" });
      act(() => player.onended?.());
      expect(result.current.phase).toBe("listening");
    }
    expect(turn).toHaveBeenCalledTimes(3);
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("falls back to OmniVoice if the system voice is unavailable", async () => {
    useVoicePreferences.setState({ speechEngine: "fast" });
    fetchMock.mockImplementation(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/health")) return { json: async () => ({ wake_ready: true, tts_ready: true, transcription_ready: true }) };
      if (JSON.parse(String(options?.body)).engine === "system") return { ok: false };
      return { ok: true, arrayBuffer: async () => new ArrayBuffer(8) };
    });
    const { result } = renderHook(() => useLocalVoiceConversation(vi.fn().mockResolvedValue("Reply")));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    act(() => Socket.latest.emit({ type: "final", text: "hello" }));
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/tts")).map(([, options]) => JSON.parse(options.body).engine)).toEqual(["system", "omnivoice"]);
    act(() => player.onended?.());
    expect(result.current.phase).toBe("listening");
  });

  it("keeps the same microphone session across muted turns and reads saved pause settings", async () => {
    useVoicePreferences.setState({ spokenReplies: false, silenceSeconds: 2 });
    const turn = vi.fn().mockResolvedValue("Text reply");
    const { result } = renderHook(() => useLocalVoiceConversation(turn));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    const ws = Socket.latest;
    for (const text of ["first turn", "second turn"]) {
      act(() => ws.emit({ type: "final", text }));
      await waitFor(() => expect(result.current.phase).toBe("listening"));
    }
    expect(turn).toHaveBeenCalledTimes(2);
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith("/tts"))).toBe(false);
    expect(JSON.parse(ws.send.mock.calls.at(-1)![0])).toMatchObject({ mode: "conversation", silence_seconds: 2 });
  });

  it("resumes listening when the speech response body stalls", async () => {
    const { result } = renderHook(() => useLocalVoiceConversation(vi.fn().mockResolvedValue("Reply")));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    fetchMock.mockResolvedValue({ ok: true, arrayBuffer: () => new Promise(() => {}) });
    vi.useFakeTimers();
    await act(async () => Socket.latest.emit({ type: "final", text: "hello" }));
    await act(async () => vi.advanceTimersByTimeAsync(90_001));
    expect(result.current.phase).toBe("listening");
    expect(result.current.error).toContain("Speech took too long on CPU");
  });

  it("muting playback resumes listening and accepts a second turn", async () => {
    const turn = vi.fn().mockResolvedValue("Reply");
    const { result } = renderHook(() => useLocalVoiceConversation(turn));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    act(() => Socket.latest.emit({ type: "final", text: "first" }));
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    act(() => useVoicePreferences.getState().setSpokenReplies(false));
    expect(result.current.phase).toBe("listening");
    act(() => Socket.latest.emit({ type: "final", text: "second" }));
    await waitFor(() => expect(turn).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.phase).toBe("listening"));
  });

  it("uses a watchdog when audio playback never emits ended", async () => {
    const { result } = renderHook(() => useLocalVoiceConversation(vi.fn().mockResolvedValue("Reply")));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    vi.useFakeTimers();
    await act(async () => Socket.latest.emit({ type: "final", text: "hello" }));
    expect(result.current.phase).toBe("speaking");
    await act(async () => vi.advanceTimersByTimeAsync(31_501));
    expect(result.current.phase).toBe("listening");
    expect(player.stop).toHaveBeenCalled();
  });

  it("previews drafts through finalization and sends only the corrected final once", async () => {
    const turn = vi.fn().mockResolvedValue("Done");
    const { result } = renderHook(() => useLocalVoiceConversation(turn));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    act(() => Socket.latest.emit({ type: "partial", text: "make a for" }));
    expect(result.current.transcript).toBe("make a for");
    act(() => Socket.latest.emit({ type: "partial", text: "make a forest at night" }));
    act(() => Socket.latest.emit({ type: "hold" }));
    expect(result.current.transcribing).toBe(true);
    expect(result.current.transcript).toBe("make a forest at night");
    expect(turn).not.toHaveBeenCalled();
    act(() => Socket.latest.emit({ type: "final", text: "Make a forest at night." }));
    act(() => Socket.latest.emit({ type: "final", text: "duplicate" }));
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    expect(turn).toHaveBeenCalledExactlyOnceWith("Make a forest at night.", expect.any(Function));
    act(() => player.onended?.());
    expect(result.current.transcript).toBe("");
    act(() => Socket.latest.emit({ type: "partial", text: "noise" }));
    act(() => Socket.latest.emit({ type: "hold" }));
    act(() => Socket.latest.emit({ type: "listen" }));
    expect(result.current.transcript).toBe("");
    expect(result.current.transcribing).toBe(false);
  });

  it("keeps an activated wake session listening after speech synthesis fails", async () => {
    const turn = vi.fn().mockResolvedValue("Saved chat reply");
    const { result } = renderHook(() => useLocalVoiceConversation(turn));
    act(() => result.current.arm());
    await waitFor(() => expect(result.current.armed).toBe(true));
    fetchMock.mockImplementation(async () => ({ ok: false, json: async () => ({}) }));
    act(() => Socket.latest.emit({ type: "wake", text: "hello" }));
    await waitFor(() => expect(result.current.error).toContain("reply"));
    expect(result.current.phase).toBe("listening");
    act(() => Socket.latest.emit({ type: "final", text: "another message" }));
    await waitFor(() => expect(turn).toHaveBeenCalledTimes(2));
  });

  it("arms locally without sending a conversation, then sends only the wake command and speaks through OmniVoice", async () => {
    const turn = vi.fn().mockResolvedValue("Here is your scene.");
    const { result, unmount } = renderHook(() => useLocalVoiceConversation(turn));
    act(() => result.current.arm());
    await waitFor(() => expect(result.current.armed).toBe(true));
    expect(turn).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalled();
    act(() => Socket.latest.emit({ type: "wake", text: "make a forest" }));
    act(() => Socket.latest.emit({ type: "final", text: "duplicate" }));
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    expect(turn).toHaveBeenCalledExactlyOnceWith("make a forest", expect.any(Function));
    expect(fetchMock.mock.calls.every(([url]) => url.startsWith("http://127.0.0.1:8002/"))).toBe(true);
    act(() => player.onended?.());
    expect(result.current.phase).toBe("listening");
    act(() => Socket.latest.emit({ type: "final", text: "goodbye" }));
    expect(result.current.phase).toBe("off"); expect(result.current.armed).toBe(true);
    expect(turn).toHaveBeenCalledTimes(1);
    unmount(); expect(track.stop).toHaveBeenCalled(); expect(Socket.latest.close).toHaveBeenCalled();
  });

  it("does not synthesize a late reply after disarming", async () => {
    let resolve!: (value: string) => void;
    const turn = vi.fn(() => new Promise<string>((done) => { resolve = done; }));
    const { result } = renderHook(() => useLocalVoiceConversation(turn));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("listening"));
    act(() => Socket.latest.emit({ type: "final", text: "hello" }));
    act(() => result.current.stop());
    await act(async () => resolve("late answer"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("off");
  });

  it("releases a microphone granted after cancellation", async () => {
    let resolve!: (value: MediaStream) => void;
    vi.mocked(navigator.mediaDevices.getUserMedia).mockImplementation(() => new Promise((done) => { resolve = done; }));
    const { result } = renderHook(() => useLocalVoiceConversation(vi.fn()));
    act(() => result.current.arm());
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled());
    act(() => result.current.stop());
    await act(async () => resolve({ getTracks: () => [track] } as unknown as MediaStream));
    expect(track.stop).toHaveBeenCalled(); expect(result.current.armed).toBe(false);
  });

  it("reports a local runtime failure without falling back to cloud speech", async () => {
    fetchMock.mockRejectedValue(new Error("Local voice offline"));
    const { result } = renderHook(() => useLocalVoiceConversation(vi.fn()));
    act(() => result.current.arm());
    await waitFor(() => expect(result.current.error).toContain("offline"));
    expect(result.current.armed).toBe(false);
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
  });
});
