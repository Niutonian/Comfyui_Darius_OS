"use client";

import { useEffect, useRef, useState } from "react";

type Recognition = {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((event: { results: { isFinal: boolean; 0: { transcript: string } }[] }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; abort(): void; stop(): void;
};
type VoiceWindow = Window & { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };

export function useVoiceConversation(onTurn: (text: string) => Promise<string>) {
  const [phase, setPhase] = useState<"off" | "listening" | "thinking" | "speaking">("off");
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const active = useRef(false);
  const generation = useRef(0);
  const recognition = useRef<Recognition | null>(null);
  const turn = useRef(onTurn);
  useEffect(() => { turn.current = onTurn; }, [onTurn]);

  function stop() {
    active.current = false;
    generation.current += 1;
    recognition.current?.abort();
    recognition.current = null;
    window.speechSynthesis?.cancel();
    setPhase("off");
    setTranscript("");
  }

  function listen(token: number) {
    if (!active.current || generation.current !== token) return;
    const voiceWindow = window as VoiceWindow;
    const Engine = voiceWindow.SpeechRecognition ?? voiceWindow.webkitSpeechRecognition;
    if (!Engine) { stop(); setError("Voice recognition is unavailable in this browser. Try Chrome or Edge, or type below."); return; }
    const engine = new Engine();
    recognition.current = engine;
    engine.lang = navigator.language || "en-US";
    engine.continuous = false;
    engine.interimResults = true;
    let submitted = false;
    engine.onresult = (event) => {
      if (!active.current || generation.current !== token || submitted) return;
      const text = Array.from(event.results).map((result) => result[0].transcript).join(" ").trim();
      setTranscript(text);
      if (!Array.from(event.results).some((result) => result.isFinal) || !text) return;
      submitted = true;
      engine.stop();
      setPhase("thinking");
      void turn.current(text).then((reply) => {
        if (!active.current || generation.current !== token) return;
        setTranscript("");
        if (!window.speechSynthesis || !reply) { stop(); setError("Spoken replies are unavailable. You can read Darius’s reply below."); return; }
        const utterance = new SpeechSynthesisUtterance(reply);
        utterance.lang = engine.lang;
        utterance.onend = () => listen(token);
        utterance.onerror = () => { if (active.current && generation.current === token) { stop(); setError("The spoken reply was interrupted. Start voice again to continue."); } };
        setPhase("speaking");
        window.speechSynthesis.speak(utterance);
      }).catch((err: unknown) => {
        if (generation.current !== token) return;
        stop();
        setError(err instanceof Error ? err.message : "Darius could not reply. Please retry your message.");
      });
    };
    engine.onerror = (event) => {
      if (!active.current || generation.current !== token || submitted) return;
      stop();
      setError(event.error === "not-allowed" ? "Microphone access was denied. Allow microphone access in your browser and try again." : `Voice stopped (${event.error}). Start voice to try again.`);
    };
    engine.onend = () => {
      if (active.current && generation.current === token && !submitted) {
        stop(); setError("No speech was captured. Start voice when you’re ready.");
      }
    };
    setPhase("listening");
    try { engine.start(); } catch { stop(); setError("Could not start the microphone. Please try again."); }
  }

  function start() {
    stop(); setError(""); active.current = true;
    listen(generation.current);
  }

  useEffect(() => () => {
    active.current = false;
    generation.current += 1;
    recognition.current?.abort();
    window.speechSynthesis?.cancel();
  }, []);

  return { phase, transcript, error, start, stop, clearError: () => setError("") };
}
