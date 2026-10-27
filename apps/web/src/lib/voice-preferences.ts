"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export const useVoicePreferences = create<{
  silenceSeconds: number; spokenReplies: boolean; voiceDescription: string; speechEngine: "fast" | "omnivoice"; deviceVoiceURI: string;
  conversationBackend: "pipecat" | "classic"; pipecatVoice: string;
  setConversationBackend: (value: "pipecat" | "classic") => void;
  setPipecatVoice: (value: string) => void;
  setSilenceSeconds: (value: number) => void;
  setSpokenReplies: (value: boolean) => void;
  setVoiceDescription: (value: string) => void;
  setSpeechEngine: (value: "fast" | "omnivoice") => void;
  setDeviceVoiceURI: (value: string) => void;
}>()(persist((set) => ({
  silenceSeconds: 1.2, spokenReplies: true, voiceDescription: "", speechEngine: "fast", deviceVoiceURI: "",
  conversationBackend: "pipecat", pipecatVoice: "af_heart",
  setConversationBackend: (conversationBackend) => set({ conversationBackend }),
  setPipecatVoice: (pipecatVoice) => set({ pipecatVoice }),
  setSilenceSeconds: (value) => set({ silenceSeconds: Number.isFinite(value) ? Math.max(0.5, Math.min(3, value)) : 1.2 }),
  setSpokenReplies: (spokenReplies) => set({ spokenReplies }),
  setVoiceDescription: (value) => set({ voiceDescription: value.slice(0, 300) }),
  setSpeechEngine: (speechEngine) => set({ speechEngine }),
  setDeviceVoiceURI: (deviceVoiceURI) => set({ deviceVoiceURI }),
}), { name: "darius-local-voice-preferences" }));
