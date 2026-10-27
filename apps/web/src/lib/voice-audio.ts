import { useVoicePreferences } from "./voice-preferences";
import { voiceServiceUrl } from "./voice-connection";

export function voiceUrl() {
  return voiceServiceUrl("classic");
}

export async function requestVoiceAudio(text: string, signal: AbortSignal): Promise<ArrayBuffer> {
  const prefs = useVoicePreferences.getState();
  const payload = { text: text.slice(0, 600), engine: prefs.speechEngine === "omnivoice" ? "omnivoice" : "system", voice: prefs.deviceVoiceURI, voice_description: prefs.voiceDescription };
  let response = await fetch(`${voiceUrl()}/tts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal });
  if (!response.ok && payload.engine === "system" && !signal.aborted) {
    response = await fetch(`${voiceUrl()}/tts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, engine: "omnivoice" }), signal });
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof detail.detail === "string" ? detail.detail.slice(0, 300) : "Speech playback failed. Your reply is available in chat.");
  }
  return response.arrayBuffer();
}
