"use client";

import { useEffect, useState } from "react";
import { transcriptionStorageKey, voiceUrl } from "@/lib/use-local-voice-conversation";

type ProviderId = "r2t2" | "faster-whisper";

type VoiceHealth = {
  transcription_provider?: string;
  transcription_active_provider?: string;
  transcription_providers?: Partial<Record<ProviderId, boolean>>;
  transcription_error?: string;
};

const options: { id: ProviderId; title: string; detail: string }[] = [
  { id: "faster-whisper", title: "Faster-Whisper", detail: "Default. Local CPU transcription, so it does not use GPU memory." },
  { id: "r2t2", title: "Confucius4-R2T2", detail: "Optional GPU transcription. Start its Docker container before choosing this. If it fails, Darius uses Faster-Whisper." },
];

export function TranscriptionSetting() {
  const [health, setHealth] = useState<VoiceHealth | null>(null);
  const [selected, setSelected] = useState<ProviderId>(() => {
    if (typeof window === "undefined") return "faster-whisper";
    const saved = window.localStorage.getItem(transcriptionStorageKey);
    return saved === "r2t2" || saved === "faster-whisper" ? saved : "faster-whisper";
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void fetch(`${voiceUrl()}/health`).then((response) => response.json()).then((body: VoiceHealth) => {
      if (cancelled) return;
      setHealth(body);
      if (body.transcription_provider === "r2t2" || body.transcription_provider === "faster-whisper") setSelected(body.transcription_provider);
    }).catch(() => { if (!cancelled) setError("The local voice service is not running."); });
    return () => { cancelled = true; };
  }, []);

  async function choose(provider: ProviderId) {
    setSaving(true);
    setError("");
    setSelected(provider);
    window.localStorage.setItem(transcriptionStorageKey, provider);
    try {
      const response = await fetch(`${voiceUrl()}/transcription`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider }) });
      if (!response.ok) throw new Error("The voice service did not accept that transcription engine.");
      setHealth(await response.json() as VoiceHealth);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the transcription engine.");
    } finally {
      setSaving(false);
    }
  }

  return <div className="theme-options" role="radiogroup" aria-label="Transcription engine">
    {options.map((option) => {
      const ready = health?.transcription_providers?.[option.id];
      return <button key={option.id} className={`theme-option ${selected === option.id ? "selected" : ""}`} role="radio" aria-checked={selected === option.id} disabled={saving} onClick={() => void choose(option.id)} type="button">
        <span><strong>{option.title}</strong><small>{option.detail}{ready === false ? " Model is not ready on this machine." : ready ? " Ready." : ""}</small></span>
      </button>;
    })}
    {saving ? <p className="muted">Saving transcription engine…</p> : null}
    {health?.transcription_error ? <p className="muted" role="status">{health.transcription_error}</p> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </div>;
}
