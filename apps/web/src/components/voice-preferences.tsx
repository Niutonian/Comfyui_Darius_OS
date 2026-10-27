"use client";
import { useEffect, useState } from "react";
import { useVoicePreferences } from "@/lib/voice-preferences";
import { voiceUrl } from "@/lib/voice-audio";
import { VoiceDiagnostics } from "./voice-diagnostics";
import { pipecatUrl } from "@/lib/use-pipecat-voice-conversation";

const voiceStyles = [
  ["", "Default voice"], ["male", "Male"], ["female", "Female"],
  ["male, low pitch", "Male · low pitch"], ["female, low pitch", "Female · low pitch"],
  ["male, british accent", "Male · British accent"], ["female, british accent", "Female · British accent"],
  ["male, american accent", "Male · American accent"], ["female, american accent", "Female · American accent"],
  ["male, australian accent", "Male · Australian accent"], ["female, australian accent", "Female · Australian accent"],
  ["male, indian accent", "Male · Indian accent"], ["female, indian accent", "Female · Indian accent"],
  ["whisper", "Whisper"],
] as const;

export function VoicePreferences() {
  const prefs = useVoicePreferences();
  const [deviceVoices, setDeviceVoices] = useState<{ name: string; lang: string }[]>([]);
  const [pipecatStatus, setPipecatStatus] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void fetch(`${voiceUrl()}/voices`, { signal: controller.signal }).then((response) => response.json()).then((data) => setDeviceVoices(Array.isArray(data.voices) ? data.voices : [])).catch(() => {});
    return () => controller.abort();
  }, []);
  return <div className="settings-note">
    <label>Local conversation engine<select aria-label="Local conversation engine" value={prefs.conversationBackend} onChange={(event) => prefs.setConversationBackend(event.target.value as "pipecat" | "classic")}><option value="pipecat">Pipecat · CPU streaming</option><option value="classic">Classic local voice</option></select></label>
    {prefs.conversationBackend === "pipecat" ? <><span>Pipecat keeps listening during replies and streams Kokoro speech on CPU. Your chosen Darius model and workflow approvals are unchanged. Start listening again after switching engines.</span>
      <label>Pipecat voice<select aria-label="Pipecat voice" value={prefs.pipecatVoice} onChange={(event) => prefs.setPipecatVoice(event.target.value)}><option value="af_heart">Heart · American female</option><option value="af_bella">Bella · American female</option><option value="af_nicole">Nicole · American female</option><option value="am_adam">Adam · American male</option><option value="am_michael">Michael · American male</option><option value="bf_emma">Emma · British female</option><option value="bm_george">George · British male</option></select></label>
      <button type="button" className="secondary-button" onClick={() => { void fetch(`${pipecatUrl()}/health`, { signal: AbortSignal.timeout(5000) }).then((response) => response.json()).then((data) => setPipecatStatus(data.ready ? "Pipecat is ready · CPU only · Silero + Smart Turn · Kokoro streaming." : data.error || "Pipecat is warming up. Classic voice is still available.")).catch(() => setPipecatStatus("Pipecat is offline. Run scripts/setup-pipecat.ps1 and restart Darius, or choose Classic voice.")); }}>Check Pipecat</button>{pipecatStatus ? <p role="status">{pipecatStatus}</p> : null}</> : null}
    <label>Pause to send <select aria-label="Pause before sending voice message" value={prefs.silenceSeconds} onChange={(event) => prefs.setSilenceSeconds(Number(event.target.value))}><option value={0.8}>0.8 seconds</option><option value={1.2}>1.2 seconds</option><option value={2}>2 seconds</option><option value={3}>3 seconds</option></select></label>
    <label><input type="checkbox" role="switch" checked={prefs.spokenReplies} onChange={(event) => prefs.setSpokenReplies(event.target.checked)} /> Spoken replies</label>
    <span>When off, you can still dictate. Darius replies in text and immediately listens for your next turn.</span>
    <label>Classic spoken reply engine <select aria-label="Spoken reply engine" value={prefs.speechEngine ?? "fast"} onChange={(event) => prefs.setSpeechEngine(event.target.value as "fast" | "omnivoice")}><option value="fast">Fast device voice</option><option value="omnivoice">OmniVoice · slower CPU voice</option></select></label>
    <span>Fast uses an installed Windows voice on the Darius server. If it is unavailable, Darius tries OmniVoice.</span>
    {prefs.speechEngine !== "omnivoice" ? <label>Device voice <select aria-label="Device voice" value={deviceVoices.some((voice) => voice.name === prefs.deviceVoiceURI) ? prefs.deviceVoiceURI : ""} disabled={!deviceVoices.length} onChange={(event) => prefs.setDeviceVoiceURI(event.target.value)}><option value="">Default English voice</option>{deviceVoices.map((voice) => <option key={voice.name} value={voice.name}>{voice.name} ({voice.lang})</option>)}</select></label> : null}
    {prefs.speechEngine === "omnivoice" ? <><label>OmniVoice style <select aria-label="Local voice style" value={voiceStyles.some(([value]) => value === prefs.voiceDescription) ? prefs.voiceDescription : ""} onChange={(event) => prefs.setVoiceDescription(event.target.value)}>{voiceStyles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {!voiceStyles.some(([value]) => value === prefs.voiceDescription) ? <span>Your old voice description is unsupported. Darius will use the default voice until you select a style.</span> : null}
      <span>These are the English styles supported by the installed OmniVoice model.</span></> : null}
    <VoiceDiagnostics />
  </div>;
}
