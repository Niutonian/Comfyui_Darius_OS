import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useVoiceConversation } from "./use-voice-conversation";

class FakeRecognition {
  static latest: FakeRecognition;
  constructor() { FakeRecognition.latest = this; }
  start = vi.fn(); stop = vi.fn(); abort = vi.fn();
  onresult?: (event: unknown) => void;
  onerror?: (event: unknown) => void;
  final(text: string) { this.onresult?.({ results: [{ isFinal: true, 0: { transcript: text } }] }); }
}
class FakeUtterance { constructor(public text: string) {} onend?: () => void; }
afterEach(() => vi.unstubAllGlobals());
function setup() {
  vi.stubGlobal("SpeechRecognition", FakeRecognition);
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  const speech = { speak: vi.fn(), cancel: vi.fn() };
  vi.stubGlobal("speechSynthesis", speech);
  return speech;
}
describe("voice conversation", () => {
  it("leaves thinking and exposes a failed AI reply instead of silently stopping", async () => {
    const speech = setup();
    const { result } = renderHook(() => useVoiceConversation(vi.fn().mockRejectedValue(new Error("The AI service is rate limited."))));
    act(() => result.current.start());
    act(() => FakeRecognition.latest.final("Hello"));
    await waitFor(() => expect(result.current.phase).toBe("off"));
    expect(result.current.error).toContain("rate limited");
    expect(speech.speak).not.toHaveBeenCalled();
  });

  it("submits final speech once, speaks the reply, and resumes listening", async () => {
    const speech = setup();
    const send = vi.fn().mockResolvedValue("Let’s build that scene.");
    const { result, unmount } = renderHook(() => useVoiceConversation(send));
    act(() => result.current.start());
    expect(result.current.phase).toBe("listening");
    act(() => { FakeRecognition.latest.final("A quiet forest"); FakeRecognition.latest.final("A quiet forest"); });
    await waitFor(() => expect(result.current.phase).toBe("speaking"));
    expect(send).toHaveBeenCalledExactlyOnceWith("A quiet forest");
    act(() => speech.speak.mock.calls[0][0].onend());
    expect(result.current.phase).toBe("listening");
    const recognizer = FakeRecognition.latest;
    unmount();
    expect(recognizer.abort).toHaveBeenCalled();
    expect(speech.cancel).toHaveBeenCalled();
  });
  it("does not speak a late AI reply after voice is stopped", async () => {
    const speech = setup();
    let resolve!: (text: string) => void;
    const { result } = renderHook(() => useVoiceConversation(() => new Promise<string>((done) => { resolve = done; })));
    act(() => result.current.start());
    act(() => FakeRecognition.latest.final("Hello"));
    act(() => result.current.stop());
    await act(async () => resolve("Hello there"));
    expect(speech.speak).not.toHaveBeenCalled();
    expect(result.current.phase).toBe("off");
  });
  it("reports permission denial and releases the microphone", () => {
    setup();
    const { result } = renderHook(() => useVoiceConversation(vi.fn()));
    act(() => result.current.start());
    act(() => FakeRecognition.latest.onerror?.({ error: "not-allowed" }));
    expect(result.current.phase).toBe("off");
    expect(result.current.error).toContain("denied");
    expect(FakeRecognition.latest.abort).toHaveBeenCalled();
  });
});
