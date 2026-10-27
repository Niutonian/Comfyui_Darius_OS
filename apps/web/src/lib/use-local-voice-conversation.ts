"use client";
import { microphoneProblem } from "./voice-connection";

import { useEffect, useRef, useState } from "react";
import { useVoicePreferences } from "./voice-preferences";
import { requestVoiceAudio, voiceUrl } from "./voice-audio";
import { speechChunks } from "./reply-stream";
export { voiceUrl } from "./voice-audio";

export const transcriptionStorageKey = "darius-transcription-provider-v2";

type Mode = "wake" | "conversation" | "paused" | "interrupt";
type Phase = "off" | "listening" | "thinking" | "speaking";

export function useLocalVoiceConversation(onTurn: (text: string, onDelta?: (text: string) => void) => Promise<string>, blocked = false) {
  const [phase, setPhase] = useState<Phase>("off");
  const [armed, setArmed] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const [transcribing, setTranscribing] = useState(false);
  const [waitingForReply, setWaitingForReply] = useState(false);
  const silenceSeconds = useVoicePreferences((state) => state.silenceSeconds);
  const spokenReplies = useVoicePreferences((state) => state.spokenReplies);
  const turn = useRef(onTurn);
  const unavailable = useRef(blocked);
  const session = useRef(0);
  const wakeEnabled = useRef(false);
  const mode = useRef<Mode>("paused");
  const socket = useRef<WebSocket | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const context = useRef<AudioContext | null>(null);
  const playback = useRef<AudioBufferSourceNode | null>(null);
  const request = useRef<AbortController | null>(null);
  const idle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const capture = useRef(true);
  const pendingTurn = useRef<string | null>(null);
  const effects = useRef({ submit, start, release });
  // Effects use the latest actions without reconnecting or replaying a turn
  // merely because a render created new function identities.
  useEffect(() => { effects.current = { submit, start, release }; });
  useEffect(() => { turn.current = onTurn; }, [onTurn]);
  useEffect(() => {
    unavailable.current = blocked;
    if (!blocked && pendingTurn.current && socket.current?.readyState === WebSocket.OPEN) {
      const text = pendingTurn.current; pendingTurn.current = null;
      setWaitingForReply(false);
      changeMode("conversation"); void effects.current.submit(text);
    }
  }, [blocked]);

  function release() {
    session.current += 1;
    pendingTurn.current = null;
    mode.current = "paused";
    wakeEnabled.current = false;
    if (idle.current) clearTimeout(idle.current);
    idle.current = null;
    request.current?.abort(); request.current = null;
    playback.current?.stop(); playback.current = null;
    socket.current?.close(); socket.current = null;
    stream.current?.getTracks().forEach((track) => track.stop()); stream.current = null;
    void context.current?.close().catch(() => {}); context.current = null;
  }

  function stop() {
    release(); setPhase("off"); setArmed(false); setConnecting(false); setTranscript(""); setTranscribing(false);
    setWaitingForReply(false);
  }

  function changeMode(next: Mode) {
    if (next === "wake" || next === "conversation") { setTranscript(""); setTranscribing(false); }
    mode.current = next;
    capture.current = next !== "paused";
    if (idle.current) clearTimeout(idle.current);
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ mode: next, epoch: session.current, silence_seconds: useVoicePreferences.getState().silenceSeconds }));
  }

  function endConversation() {
    if (!wakeEnabled.current) { stop(); return; }
    // Invalidate any outstanding reply before returning to wake listening.
    session.current += 1;
    pendingTurn.current = null;
    setWaitingForReply(false);
    request.current?.abort();
    playback.current?.stop(); playback.current = null;
    changeMode("wake"); setPhase("off"); setTranscript("");
  }


  async function submit(text: string) {
    if (mode.current !== "conversation") return;
    setTranscribing(false);
    if (!text.trim()) { changeMode("conversation"); return; }
    if (/^(?:stop|end conversation|stop listening|goodbye(?: darius)?)\s*[.!?]*$/i.test(text)) { endConversation(); return; }
    if (unavailable.current) {
      pendingTurn.current = text;
      setWaitingForReply(true);
      changeMode("paused"); setPhase("thinking"); setTranscript(text);
      return;
    }
    const token = session.current;
    changeMode("paused"); setPhase("thinking"); setTranscript(text);
    const controller = new AbortController();
    let finished = false, received = false, preparing = false, rest = "", spoken = 0;
    const queue: string[] = [];
    let prefetched: { text: string; audio: Promise<AudioBuffer> } | null = null;
    const active = () => token === session.current && !controller.signal.aborted;
    const listen = () => {
      if (!active()) return;
      if (request.current === controller) request.current = null;
      changeMode("conversation"); setPhase("listening");
    };
    const fail = (err: unknown) => {
      if (!active()) return;
      controller.abort(); request.current = null;
      if (idle.current) clearTimeout(idle.current);
      playback.current?.stop(); playback.current = null;
      setError(err instanceof Error ? err.message : "Local voice failed. Please try again.");
      if (socket.current?.readyState === WebSocket.OPEN) { changeMode("conversation"); setPhase("listening"); }
      else stop();
    };
    async function synthesize(chunk: string): Promise<AudioBuffer> {
      let timer: ReturnType<typeof setTimeout> | undefined;
      let abort!: () => void;
      try {
        return await Promise.race([
          (async () => {
            const audio = await requestVoiceAudio(chunk, controller.signal);
            if (!active() || !context.current) throw new Error("Speech cancelled");
            await context.current.resume();
            return context.current.decodeAudioData(audio);
          })(),
          new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("Speech took too long on CPU. Your reply is in chat; listening again.")), 90_000); }),
          new Promise<never>((_, reject) => {
            abort = () => reject(new Error("Speech cancelled"));
            controller.signal.addEventListener("abort", abort, { once: true });
            if (controller.signal.aborted) abort();
          }),
        ]);
      } finally { clearTimeout(timer); controller.signal.removeEventListener("abort", abort); }
    }
    function prime() {
      if (!active() || prefetched || !queue.length || !playback.current) return;
      const audio = synthesize(queue[0]);
      // A rejected prefetch is handled when its turn reaches playback.
      void audio.catch(() => {});
      prefetched = { text: queue[0], audio };
    }
    async function pump() {
      if (!active() || preparing || playback.current) { prime(); return; }
      const chunk = queue.shift();
      if (!chunk) { if (finished) listen(); return; }
      request.current = controller;
      preparing = true;
      try {
        const audio = prefetched?.text === chunk ? prefetched.audio : synthesize(chunk);
        prefetched = null;
        const buffer = await audio;
        if (!active() || !context.current) return;
        const source = context.current.createBufferSource(); playback.current = source;
        source.buffer = buffer; source.connect(context.current.destination);
        source.onended = () => {
          if (!active() || playback.current !== source) return;
          if (idle.current) clearTimeout(idle.current);
          playback.current = null;
          if (queue.length || !finished) { setPhase("thinking"); void pump(); }
          else listen();
        };
        setTranscript(""); setPhase("speaking"); source.start();
        if (mode.current !== "interrupt") changeMode("interrupt");
        prime();
        idle.current = setTimeout(() => {
          if (!active() || playback.current !== source) return;
          source.stop(); source.onended?.(new Event("ended"));
        }, (Number.isFinite(buffer.duration) ? buffer.duration * 1000 : 30_000) + 1500);
      } catch (err) { fail(err); }
      finally { preparing = false; }
    }
    function enqueue(delta: string, final = false) {
      if (!active() || !useVoicePreferences.getState().spokenReplies) return;
      rest += delta;
      const split = speechChunks(rest, final); rest = split.rest;
      for (const chunk of split.chunks) {
        // Preserve the existing spoken-reply budget, rather than reading long essays aloud.
        const bounded = chunk.slice(0, Math.max(0, 600 - spoken));
        if (bounded.trim()) { queue.push(bounded); spoken += bounded.length; }
      }
      void pump();
    }
    try {
      const reply = await turn.current(text, (delta) => { received = true; enqueue(delta); });
      if (!active()) return;
      finished = true;
      enqueue(received ? "" : reply, true);
      if (!preparing && !playback.current && !queue.length) listen();
    } catch (err) {
      fail(err);
    }
  }

  async function connect(wake: boolean) {
    stop(); setError(""); setConnecting(true);
    const token = session.current;
    try {
      const problem = microphoneProblem();
      if (problem) throw new Error(problem);
      // Resume during the user's click so subsequent local audio can play hands-free.
      const audio = new AudioContext({ sampleRate: 16000 }); context.current = audio;
      await audio.resume();
      const savedProvider = window.localStorage.getItem(transcriptionStorageKey);
      if (savedProvider === "r2t2" || savedProvider === "faster-whisper") {
        await fetch(`${voiceUrl()}/transcription`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: savedProvider }), signal: AbortSignal.timeout(5000) }).catch(() => undefined);
      }
      const health = await fetch(`${voiceUrl()}/health`, { signal: AbortSignal.timeout(5000) }).then((r) => r.json()) as { wake_ready: boolean; tts_ready: boolean; transcription_ready: boolean };
      if (token !== session.current) return;
      if (!health.wake_ready || !health.transcription_ready) throw new Error("Local transcription is not ready. Check the local voice service and its speech models.");
      const mic = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (token !== session.current) { mic.getTracks().forEach((track) => track.stop()); return; }
      stream.current = mic;
      await audio.audioWorklet.addModule("/voice-capture.js");
      if (token !== session.current) return;
      const serviceUrl = voiceUrl();
      const ws = new WebSocket(`${serviceUrl.replace("http:", "ws:").replace("https:", "wss:")}/listen`); socket.current = ws;
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("Local voice connection timed out.")), 15_000);
        ws.onerror = () => { clearTimeout(timer); reject(new Error("Cannot connect to the local voice service.")); };
        ws.onclose = () => { clearTimeout(timer); reject(new Error("Local voice connection closed.")); };
        ws.onmessage = (event) => {
          const data = JSON.parse(event.data);
          if (data.type === "ready") { clearTimeout(timer); resolve(); }
          if (data.type === "error") { clearTimeout(timer); reject(new Error(data.message)); }
        };
      });
      if (token !== session.current) return;
      wakeEnabled.current = wake; setArmed(wake); setConnecting(false);
      changeMode(wake ? "wake" : "conversation"); setPhase(wake ? "off" : "listening");
      ws.onmessage = (event) => {
        if (socket.current !== ws) return;
        const data = JSON.parse(event.data) as { type: string; text: string; message: string; epoch?: number };
        if (data.epoch !== undefined && data.epoch !== session.current) return;
        if (data.type === "interrupt" && mode.current === "interrupt") {
          start();
        } else if (data.type === "wake" && mode.current === "wake") {
          if (unavailable.current) { changeMode("wake"); return; }
          changeMode("conversation"); setPhase("listening");
          if (data.text) void submit(data.text);
        } else if (data.type === "hold") {
          capture.current = false;
          setTranscribing(true);
          if (idle.current) clearTimeout(idle.current);
        } else if (data.type === "listen" && mode.current === "conversation") {
          capture.current = true;
          setTranscribing(false);
          setTranscript("");
        } else if (data.type === "partial" && mode.current === "conversation") {
          setTranscript(data.text);
          if (idle.current) clearTimeout(idle.current);
        } else if (data.type === "final" && (mode.current === "conversation" || !capture.current)) void submit(data.text);
        else if (data.type === "error") { setTranscribing(false); setError(data.message); if (mode.current !== "paused") { capture.current = true; } }
      };
      ws.onclose = ws.onerror = () => { if (socket.current === ws) { stop(); setError("Local voice disconnected. Start voice again to reconnect."); } };
      const worklet = new AudioWorkletNode(audio, "darius-voice-capture");
      worklet.port.onmessage = (event) => {
        if (socket.current === ws && ws.readyState === WebSocket.OPEN && capture.current && mode.current !== "paused" && ws.bufferedAmount < 32000) {
          ws.send(event.data);
        }
      };
      const mute = audio.createGain(); mute.gain.value = 0;
      audio.createMediaStreamSource(mic).connect(worklet); worklet.connect(mute); mute.connect(audio.destination);
      mic.getTracks().forEach((track) => { track.onended = () => { if (stream.current === mic) stop(); }; });
    } catch (err) {
      if (token !== session.current) return;
      stop();
      setError(err instanceof DOMException && err.name === "NotAllowedError" ? "Allow microphone access to enable local voice." : err instanceof Error ? err.message : "Local voice is unavailable.");
    }
  }

  useEffect(() => () => { effects.current.release(); }, []);
  useEffect(() => {
    if (!spokenReplies && (request.current || playback.current)) effects.current.start();
  }, [spokenReplies]);
  function start() {
    if (pendingTurn.current) return;
    if (socket.current?.readyState === WebSocket.OPEN) {
      session.current += 1; request.current?.abort(); playback.current?.stop(); playback.current = null;
      changeMode("conversation"); setPhase("listening"); setTranscript(""); setError("");
    } else void connect(false);
  }
  return { phase, armed, connecting, transcript, error, transcribing, waitingForReply, silenceSeconds,
    setSilenceSeconds: useVoicePreferences.getState().setSilenceSeconds,
    start, interrupt: start, arm: () => void connect(true), stop, endConversation, clearError: () => setError("") };
}
