"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "./api-client";
import { microphoneProblem } from "./voice-connection";

type Phase = "off" | "listening" | "thinking" | "speaking";

/** GPT-Live 1 browser transport. The API key never reaches this hook. */
export function useLiveVoiceConversation(onTurn: (text: string) => Promise<string>, blocked = false, projectId: string | null = null) {
  const [phase, setPhase] = useState<Phase>("off");
  const [connecting, setConnecting] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const turn = useRef(onTurn);
  const unavailable = useRef(blocked);
  const peer = useRef<RTCPeerConnection | null>(null);
  const events = useRef<RTCDataChannel | null>(null);
  const microphone = useRef<MediaStream | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  useEffect(() => { turn.current = onTurn; }, [onTurn]);
  useEffect(() => { unavailable.current = blocked; }, [blocked]);

  function release() {
    events.current?.close(); events.current = null;
    peer.current?.close(); peer.current = null;
    microphone.current?.getTracks().forEach((track) => track.stop()); microphone.current = null;
    if (audio.current) audio.current.srcObject = null;
    audio.current = null;
  }

  function stop() {
    release(); setPhase("off"); setConnecting(false); setTranscript("");
  }

  async function start() {
    if (unavailable.current || connecting || phase !== "off") return;
    stop(); setError(""); setConnecting(true);
    const connection = new RTCPeerConnection(); peer.current = connection;
    try {
      const problem = microphoneProblem();
      if (problem) throw new Error(problem);
      const output = document.createElement("audio"); output.autoplay = true; audio.current = output;
      connection.ontrack = (event) => { output.srcObject = event.streams[0] ?? new MediaStream([event.track]); void output.play().catch(() => {}); };
      const mic = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (peer.current !== connection) { mic.getTracks().forEach((track) => track.stop()); return; }
      microphone.current = mic; mic.getTracks().forEach((track) => connection.addTrack(track, mic));
      const channel = connection.createDataChannel("oai-events"); events.current = channel;
      channel.onopen = () => { if (peer.current === connection) { setConnecting(false); setPhase("listening"); } };
      channel.onmessage = (message) => {
        if (peer.current !== connection) return;
        try {
          const event = JSON.parse(message.data) as { type?: string; transcript?: string; delta?: string };
          if (event.type === "session.started") { setConnecting(false); setPhase("listening"); return; }
          if (event.type === "input_audio_buffer.speech_started") { setPhase("listening"); return; }
          if (event.type === "response.created") { setPhase("speaking"); return; }
          if (event.type === "response.done") { setPhase("listening"); return; }
          if (event.type === "conversation.item.input_audio_transcription.completed" && event.transcript?.trim()) {
            const text = event.transcript.trim(); setTranscript(text); setPhase("thinking");
            void turn.current(text).catch((err: unknown) => setError(err instanceof Error ? err.message : "Darius could not process that request."));
          }
        } catch { /* Ignore non-JSON transport frames. */ }
      };
      channel.onerror = () => { if (peer.current === connection) setError("GPT-Live disconnected from its event channel."); };
      const offer = await connection.createOffer(); await connection.setLocalDescription(offer);
      if (peer.current !== connection) return;
      if (connection.iceGatheringState !== "complete") await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error("Timed out while preparing the GPT-Live connection.")), 10_000);
        const onState = () => { if (connection.iceGatheringState === "complete") { clearTimeout(timeout); connection.removeEventListener("icegatheringstatechange", onState); resolve(); } };
        connection.addEventListener("icegatheringstatechange", onState); onState();
      });
      const sdp = connection.localDescription?.sdp;
      if (peer.current !== connection) return;
      if (!sdp) throw new Error("GPT-Live did not produce a local SDP offer.");
      const response = await fetch(`${API_BASE}/live/session`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sdp, project_id: projectId }), signal: AbortSignal.timeout(45_000) });
      if (peer.current !== connection) return;
      if (!response.ok) { const body = await response.json().catch(() => ({})) as { detail?: string }; throw new Error(body.detail || "GPT-Live session creation failed."); }
      const result = await response.json() as { transport?: { sdp?: string } };
      if (peer.current !== connection) return;
      if (!result.transport?.sdp) throw new Error("GPT-Live returned no SDP answer.");
      await connection.setRemoteDescription({ type: "answer", sdp: result.transport.sdp });
      if (channel.readyState === "open") setPhase("listening");
    } catch (err) {
      if (peer.current !== connection) return;
      release(); setConnecting(false); setPhase("off");
      setError(err instanceof DOMException && err.name === "NotAllowedError" ? "Allow microphone access to use GPT-Live." : err instanceof Error ? err.message : "GPT-Live is unavailable.");
    }
  }

  function endConversation() { stop(); }
  useEffect(() => () => release(), []);
  return { phase, armed: false, connecting, transcript, error, start, arm: start, stop, endConversation, clearError: () => setError("") };
}
