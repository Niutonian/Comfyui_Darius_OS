"use client";

import { useEffect, useRef, useState } from "react";
import { useVoicePreferences } from "./voice-preferences";
import { speechChunks } from "./reply-stream";
import { microphoneProblem, voiceServiceUrl } from "./voice-connection";

type Phase = "off" | "listening" | "thinking" | "speaking";
type Turn = { id: string; text: string };
export function pipecatUrl() {
  return voiceServiceUrl("pipecat");
}

/** Pipecat handles audio; the existing Darius callback owns all chat/tools/jobs. */
export function usePipecatVoiceConversation(onTurn: (text: string, onDelta?: (text: string) => void) => Promise<string>, blocked = false) {
  const [phase, setPhase] = useState<Phase>("off");
  const [connecting, setConnecting] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const [transcribing, setTranscribing] = useState(false);
  const [waitingForReply, setWaitingForReply] = useState(false);
  const turn = useRef(onTurn); turn.current = onTurn;
  const unavailable = useRef(blocked); unavailable.current = blocked;
  const socket = useRef<WebSocket | null>(null);
  const audio = useRef<AudioContext | null>(null);
  const mic = useRef<MediaStream | null>(null);
  const nodes = useRef(new Set<AudioBufferSourceNode>());
  const nextTime = useRef(0);
  const generation = useRef(0);
  const currentTurn = useRef("");
  const working = useRef(false);
  const pending = useRef<Turn | null>(null);
  const audioDone = useRef(false);
  const spoken = useVoicePreferences((state) => state.spokenReplies);
  const silenceSeconds = useVoicePreferences((state) => state.silenceSeconds);
  const voice = useVoicePreferences((state) => state.pipecatVoice);
  const effects = useRef({ drain, configure, release });
  useEffect(() => { effects.current = { drain, configure, release }; });

  function send(value: object) {
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify(value));
  }
  function silence() {
    for (const node of nodes.current) { node.onended = null; try { node.stop(); } catch { /* Already ended. */ } }
    nodes.current.clear(); nextTime.current = 0; audioDone.current = false;
  }
  function release() {
    generation.current += 1; currentTurn.current = ""; pending.current = null;
    silence();
    const old = socket.current; socket.current = null; old?.close();
    mic.current?.getTracks().forEach((track) => track.stop()); mic.current = null;
    void audio.current?.close().catch(() => {}); audio.current = null;
  }
  function stop() {
    release(); setPhase("off"); setConnecting(false); setTranscript(""); setTranscribing(false); setWaitingForReply(false);
  }
  function configure() {
    const prefs = useVoicePreferences.getState();
    send({ type: "configure", mode: "conversation", voice: prefs.pipecatVoice, silence_seconds: prefs.silenceSeconds });
  }
  function interrupt() {
    if (!socket.current) { void start(); return; }
    currentTurn.current = ""; silence(); send({ type: "interrupt" });
    setPhase("listening"); setTranscribing(false); setTranscript("");
  }
  function drain() {
    if (working.current || unavailable.current || !pending.current || !socket.current) return;
    const item = pending.current; pending.current = null;
    setWaitingForReply(false); void respond(item);
  }
  async function respond(item: Turn) {
    const connection = generation.current;
    working.current = true; setTranscribing(false); setPhase("thinking"); setTranscript(item.text);
    let rest = "", received = false, length = 0;
    function enqueue(delta: string, final = false) {
      if (connection !== generation.current || currentTurn.current !== item.id) return;
      rest += delta;
      const split = speechChunks(rest, final); rest = split.rest;
      for (const part of split.chunks) {
        const text = part.slice(0, Math.max(0, 600 - length)); length += text.length;
        if (text.trim() && useVoicePreferences.getState().spokenReplies) send({ type: "reply_chunk", turn_id: item.id, text });
      }
    }
    try {
      const result = await turn.current(item.text, (delta) => { received = true; enqueue(delta); });
      if (connection !== generation.current) return;
      enqueue(received ? "" : result, true);
      if (currentTurn.current === item.id) send({ type: "reply_end", turn_id: item.id });
    } catch (err) {
      if (connection === generation.current && currentTurn.current === item.id) {
        silence(); send({ type: "interrupt" });
        setError(err instanceof Error ? err.message : "Darius could not finish that request. Your chat is saved.");
        setPhase("listening");
      }
    } finally {
      working.current = false;
      drain(); // A newly connected session may be waiting for this saved task.
    }
  }
  function receiveTurn(item: Turn) {
    currentTurn.current = item.id; silence();
    if (/^(?:stop listening|end conversation|goodbye(?: darius)?)\s*[.!?]*$/i.test(item.text)) { stop(); return; }
    if (/^(?:(?:hey|hello)\s+)?(?:darius[,\s]+)?(?:stop|wait|stop speaking|pause speaking)\s*[.!?]*$/i.test(item.text)) { interrupt(); return; }
    if (working.current || unavailable.current) {
      pending.current = { id: item.id, text: [pending.current?.text, item.text].filter(Boolean).join("\n").slice(0, 12000) };
      setWaitingForReply(true); setTranscribing(false); setTranscript(pending.current.text); setPhase("thinking");
    } else void respond(item);
  }
  function play(data: { pcm: string; sample_rate: number; turn_id: string }) {
    const context = audio.current;
    if (!context || currentTurn.current !== data.turn_id || !useVoicePreferences.getState().spokenReplies) return;
    if (![16000, 24000].includes(data.sample_rate) || data.pcm.length > 65536) throw new Error("Invalid Pipecat audio packet");
    const raw = atob(data.pcm);
    if (raw.length % 2) throw new Error("Invalid PCM samples");
    const buffer = context.createBuffer(1, raw.length / 2, data.sample_rate);
    const samples = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) { const value = raw.charCodeAt(i * 2) | raw.charCodeAt(i * 2 + 1) << 8; samples[i] = (value >= 32768 ? value - 65536 : value) / 32768; }
    const start = Math.max(nextTime.current, context.currentTime + 0.025);
    if (start - context.currentTime > 90) throw new Error("Pipecat audio queue is full. The full reply is saved in chat.");
    const source = context.createBufferSource(); source.buffer = buffer; source.connect(context.destination);
    nodes.current.add(source); nextTime.current = start + buffer.duration;
    source.onended = () => {
      nodes.current.delete(source);
      if (!nodes.current.size && audioDone.current && socket.current) { setPhase("listening"); setTranscript(""); }
    };
    setPhase("speaking"); source.start(start);
  }
  async function start() {
    if (socket.current?.readyState === WebSocket.OPEN) { interrupt(); return; }
    if (unavailable.current || connecting) return;
    stop(); setError(""); setConnecting(true);
    const token = generation.current;
    try {
      const problem = microphoneProblem();
      if (problem) throw new Error(problem);
      const context = new AudioContext({ sampleRate: 16000 }); audio.current = context;
      await context.resume();
      let health = await fetch(`${pipecatUrl()}/health`, { signal: AbortSignal.timeout(5000) }).then((response) => response.json()) as { ready?: boolean; error?: string };
      for (let attempt = 0; !health.ready && !health.error && attempt < 12; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        if (token !== generation.current) return;
        health = await fetch(`${pipecatUrl()}/health`, { signal: AbortSignal.timeout(5000) }).then((response) => response.json());
      }
      if (token !== generation.current) return;
      if (!health.ready) throw new Error(health.error || "Pipecat is warming up or not installed. Use Classic voice in Settings while it starts.");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (token !== generation.current) { stream.getTracks().forEach((track) => track.stop()); return; }
      mic.current = stream;
      await context.audioWorklet.addModule("/voice-capture.js");
      if (token !== generation.current) return;
      const ws = new WebSocket(`${pipecatUrl().replace(/^http/, "ws")}/listen`); socket.current = ws;
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("Pipecat connection timed out. Choose Classic voice or reconnect.")), 15000);
        ws.onerror = ws.onclose = () => { clearTimeout(timer); reject(new Error("Cannot connect to Pipecat voice. Check the voice service and secure LAN gateway.")); };
        ws.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data);
            if (message.type === "ready") { clearTimeout(timer); resolve(); }
            else if (message.type === "error") { clearTimeout(timer); reject(new Error(message.message)); }
          } catch { clearTimeout(timer); reject(new Error("Invalid Pipecat handshake")); }
        };
      });
      if (token !== generation.current) return;
      configure(); setConnecting(false); setPhase("listening");
      ws.onmessage = (event) => {
        if (socket.current !== ws) return;
        try {
          const message = JSON.parse(event.data);
          if (message.type === "interruption" || message.type === "speech_started") { currentTurn.current = ""; silence(); setPhase("listening"); setTranscribing(false); }
          else if (message.type === "partial" && typeof message.text === "string") setTranscript(message.text);
          else if (message.type === "transcribing") setTranscribing(true);
          else if (message.type === "final" && typeof message.text === "string" && typeof message.turn_id === "string") receiveTurn({ id: message.turn_id, text: message.text });
          else if (message.type === "audio") play(message);
          else if (message.type === "audio_done" && message.turn_id === currentTurn.current) { audioDone.current = true; if (!nodes.current.size) { setPhase("listening"); setTranscript(""); } }
          else if (message.type === "listening") { setTranscribing(false); setPhase("listening"); }
          else if (message.type === "error") { setError(String(message.message)); setTranscribing(false); silence(); setPhase("listening"); }
        } catch (err) { setError(err instanceof Error ? err.message : "Invalid Pipecat message"); silence(); }
      };
      ws.onclose = ws.onerror = () => { if (socket.current === ws) { stop(); setError("Pipecat disconnected. Your chat and render jobs are retained. Reconnect or choose Classic voice."); } };
      const worklet = new AudioWorkletNode(context, "darius-voice-capture", { processorOptions: { frameSize: 1024 } });
      worklet.port.onmessage = (event) => {
        // Capture stays active during thinking and playback; browser AEC suppresses echo.
        if (socket.current === ws && ws.readyState === WebSocket.OPEN && ws.bufferedAmount < 32000) ws.send(event.data);
      };
      const mute = context.createGain(); mute.gain.value = 0;
      context.createMediaStreamSource(stream).connect(worklet); worklet.connect(mute); mute.connect(context.destination);
      stream.getTracks().forEach((track) => { track.onended = () => { if (mic.current === stream) stop(); }; });
    } catch (err) {
      if (token !== generation.current) return;
      stop(); setError(err instanceof DOMException && err.name === "NotAllowedError" ? "Allow microphone access for Pipecat voice." : err instanceof Error ? err.message : "Pipecat is unavailable. Choose Classic voice in Settings.");
    }
  }
  useEffect(() => { effects.current.drain(); }, [blocked]);
  useEffect(() => { if (socket.current) effects.current.configure(); }, [voice, silenceSeconds]);
  useEffect(() => { if (!spoken && socket.current) { silence(); send({ type: "interrupt" }); setPhase("listening"); } }, [spoken]);
  useEffect(() => () => effects.current.release(), []);
  return { phase, armed: false, connecting, transcript, error, transcribing, waitingForReply, silenceSeconds,
    start, interrupt, arm: start, stop, endConversation: stop, clearError: () => setError("") };
}
