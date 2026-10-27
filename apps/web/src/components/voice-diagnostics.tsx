"use client";
import { useEffect, useRef, useState } from "react";
import { requestVoiceAudio, voiceUrl } from "@/lib/voice-audio";
import { pipecatUrl } from "@/lib/use-pipecat-voice-conversation";
import { useVoicePreferences } from "@/lib/voice-preferences";
import { microphoneProblem } from "@/lib/voice-connection";

export function VoiceDiagnostics() {
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [level, setLevel] = useState(0);
  const cleanup = useRef<() => void>(() => {});
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; cleanup.current(); }, []);
  function stop() { generation.current++; cleanup.current(); cleanup.current = () => {}; setBusy(false); setLevel(0); }
  async function test(kind: "microphone" | "speaker") {
    if (kind === "microphone") {
      const problem = microphoneProblem();
      if (problem) { stop(); setStatus(problem); return; }
    }
    stop(); const token = generation.current; setBusy(true); setStatus(kind === "microphone" ? "Speak for five seconds…" : "Preparing test audio…");
    const controller = new AbortController();
    let context: AudioContext;
    try { context = new AudioContext(); }
    catch { setBusy(false); setStatus("This browser could not open an audio device. Check permissions and output settings."); return; }
    let stream: MediaStream | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let frame = 0;
    cleanup.current = () => { controller.abort(); clearTimeout(timer); cancelAnimationFrame(frame); stream?.getTracks().forEach((track) => track.stop()); void context.close().catch(() => {}); };
    try {
      await context.resume();
      if (kind === "speaker") {
        timer = setTimeout(() => controller.abort(), 90_000);
        const prefs = useVoicePreferences.getState();
        const bytes = prefs.conversationBackend === "pipecat" ? await fetch(`${pipecatUrl()}/speaker-test?voice=${encodeURIComponent(prefs.pipecatVoice)}`, { signal: controller.signal }).then(async (response) => {
          if (!response.ok) throw new Error("Pipecat speaker test failed. Check Pipecat or choose Classic voice.");
          return response.arrayBuffer();
        }) : await requestVoiceAudio("Darius speaker test. You should hear this clearly.", controller.signal);
        if (token !== generation.current) return;
        const buffer = await context.decodeAudioData(bytes);
        if (token !== generation.current) return;
        const source = context.createBufferSource(); source.buffer = buffer; source.connect(context.destination);
        setStatus("Playing test. If you cannot hear it, check this browser tab and your output device.");
        const finish = () => { if (token === generation.current) { stop(); setStatus("Speaker test finished. Did you hear the sentence?"); } };
        source.onended = finish; source.start(); clearTimeout(timer); timer = setTimeout(finish, buffer.duration * 1000 + 2000);
      } else {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (token !== generation.current) { stream.getTracks().forEach((track) => track.stop()); return; }
        const analyser = context.createAnalyser(); context.createMediaStreamSource(stream).connect(analyser);
        const samples = new Float32Array(analyser.fftSize); let peak = 0;
        const measure = () => {
          if (token !== generation.current) return;
          analyser.getFloatTimeDomainData(samples);
          const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
          peak = Math.max(peak, rms); setLevel(Math.min(1, rms * 8)); frame = requestAnimationFrame(measure);
        };
        measure(); timer = setTimeout(() => { if (token === generation.current) { stop(); setStatus(peak > 0.008 ? "Microphone signal detected. Ready to talk." : "Microphone opened, but the signal was very quiet. Check the selected input and volume."); } }, 5000);
      }
    } catch (error) { if (token === generation.current) { stop(); setStatus(error instanceof Error ? error.message : "Voice test failed."); } }
  }
  async function check() {
    try {
      if (useVoicePreferences.getState().conversationBackend === "pipecat") {
        const response = await fetch(`${pipecatUrl()}/health`, { signal: AbortSignal.timeout(5000) });
        const data = await response.json();
        setStatus(data.ready ? `Pipecat ready · CPU only · Smart Turn + Kokoro.${data.last_metrics?.transcription_ms ? ` Last transcription: ${data.last_metrics.transcription_ms}ms.` : ""}${data.last_metrics?.tts_first_audio_ms ? ` First audio: ${data.last_metrics.tts_first_audio_ms}ms.` : ""}` : data.error || "Pipecat is warming up. Classic voice is available as a fallback.");
        return;
      }
      const response = await fetch(`${voiceUrl()}/health`, { signal: AbortSignal.timeout(5000) });
      const data = await response.json();
      setStatus(data.transcription_ready ? `Transcription ready: ${data.transcription_active_provider ?? data.transcription_provider}.` : "Transcription is unavailable. Check the speech service and model files.");
    } catch { setStatus("Cannot reach the local voice service."); }
  }
  return <section className="voice-diagnostics" aria-label="Voice diagnostics"><strong>Test voice</strong><div className="control-row">
    <button type="button" className="secondary-button" disabled={busy} onClick={() => void test("microphone")}>Test microphone</button>
    <button type="button" className="secondary-button" disabled={busy} onClick={() => void test("speaker")}>Test speaker</button>
    <button type="button" className="secondary-button" disabled={busy} onClick={() => void check()}>Check service</button>
    {busy ? <button type="button" className="secondary-button" onClick={stop}>Stop test</button> : null}
    </div><meter min={0} max={1} value={level} aria-label="Microphone input level" /><p role="status">{status}</p>
    <p>Using another LAN device? <a href="/lan-setup.html" target="_blank" rel="noreferrer">Set up secure microphone access</a>.</p></section>;
}
