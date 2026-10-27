"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, Captions, Keyboard, Mic, MicOff, PhoneOff, Settings2, Volume2, VolumeX, X } from "lucide-react";
import type { DariusMood, Message } from "@/lib/types";
import { LiquidOrb } from "./liquid-orb";
import { AmbientBackground } from "./ambient-background";
import { useVoicePreferences } from "@/lib/voice-preferences";
import { useDariusStore } from "@/lib/store";
import { useWorkspaceState } from "@/lib/workspace-session";

type Props = {
  initialChat?: boolean;
  phase: "off" | "listening" | "thinking" | "speaking";
  connecting: boolean; busy: boolean; transcript: string; reply: string; error: string;
  cloud: boolean; disabled: boolean; canInterrupt: boolean;
  onStart: () => void; onStop: () => void; onClose: () => void; onEngineChange: (cloud: boolean) => void;
  onEnd?: () => void;
  draftKey?: string;
  voiceBackend?: "pipecat" | "classic"; onBackendChange?: (backend: "pipecat" | "classic") => void;
  messages?: Message[]; streamedReply?: string; sessionName?: string; projectName?: string;
  transcribing?: boolean; waitingForReply?: boolean; loading?: boolean;
  onSend?: (text: string) => Promise<unknown>;
  renderMessage?: (message: Message) => ReactNode;
  renderText?: (message: Message) => ReactNode;
  actions?: ReactNode;
  overlay?: ReactNode;
  contextPanel?: ReactNode;
};

export function FullscreenVoice({ phase, connecting, busy, transcript, reply, error, cloud, disabled,
  onStart, onStop, onClose, onEnd, draftKey = "fullscreen", onEngineChange, canInterrupt, actions, messages = [], streamedReply = "",
  sessionName = "Voice session", projectName = "Current project", transcribing = false,
  waitingForReply = false, loading = false, onSend, renderMessage, renderText, voiceBackend = "classic", onBackendChange, overlay, contextPanel, initialChat = false }: Props) {
  const dialog = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; }, [onClose]);
  const following = useRef(true);
  const scrollIntentUntil = useRef(0);
  const input = useRef<HTMLTextAreaElement>(null);
  const [captions, setCaptions] = useState(true);
  const [typing, setTyping] = useState(false);
  const [chat, setChat] = useState(initialChat);
  const showComposer = chat || typing, showText = chat || captions;
  const [draft, setDraft] = useWorkspaceState(`composer:${draftKey}:text`, "");
  const [chatAttachments] = useWorkspaceState<unknown[]>(`composer:${draftKey}:attachments`, []);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [showLatest, setShowLatest] = useState(false);
  const theme = useDariusStore((state) => state.theme);
  const spoken = useVoicePreferences((state) => state.spokenReplies);
  const setSpoken = useVoicePreferences((state) => state.setSpokenReplies);
  const history = messages.filter((message) => message.metadata.superseded !== true && (message.role === "user" || message.role === "assistant"));
  const hasConversation = Boolean(history.length || transcript || streamedReply || reply);
  const currentDraft = transcript && (phase === "listening" || transcribing || waitingForReply)
    && !(waitingForReply === false && history.at(-1)?.role === "user" && history.at(-1)?.content.trim() === transcript.trim());
  const mood: DariusMood = phase === "speaking" ? "speaking" : voiceBackend === "pipecat" && phase === "listening" ? "listening" : busy || phase === "thinking" ? "thinking" : phase === "off" ? "idle" : phase;
  const status = connecting ? "Connecting microphone…" : waitingForReply ? "Your next thought is saved" : transcribing ? "Finishing your words…"
    : phase === "speaking" ? "Darius is speaking" : phase === "listening" && voiceBackend === "pipecat" ? busy ? "Listening · your task continues" : "I’m listening" : busy ? "Working on your request" : phase === "listening" ? "I’m listening"
      : phase === "thinking" ? "Preparing your voice reply" : "Ready when you are";

  function latest() {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
    setShowLatest(false);
  }
  useEffect(() => {
    const frame = requestAnimationFrame(() => { if (following.current) latest(); });
    return () => cancelAnimationFrame(frame);
  }, [messages, streamedReply, transcript, reply, actions, captions, typing, chat]);
  useEffect(() => {
    let frame = 0;
    const follow = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => { if (following.current) latest(); });
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(follow);
    if (content.current) observer?.observe(content.current);
    if (scroller.current) observer?.observe(scroller.current);
    follow();
    return () => { observer?.disconnect(); cancelAnimationFrame(frame); };
  }, []);
  useEffect(() => { if (typing) input.current?.focus(); }, [typing]);
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow; document.body.style.overflow = "hidden";
    const siblings = Array.from(document.body.children).filter((element): element is HTMLElement => element instanceof HTMLElement && !element.contains(dialog.current));
    const previousInert = siblings.map((element) => element.inert); siblings.forEach((element) => { element.inert = true; });
    dialog.current?.focus();
    function keyboard(event: KeyboardEvent) {
      // Native media previews own Escape/Tab while they are in the top layer.
      if (document.querySelector("dialog[open]")) return;
      if (event.key === "Escape") { event.preventDefault(); close.current(); }
      if (event.key !== "Tab") return;
      const items = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), input:not(:disabled), textarea:not(:disabled), summary, a[href], [tabindex="0"]') ?? [])
        .filter((element) => {
          const closed = element.closest("details:not([open])");
          return !element.closest("[hidden], [inert], dialog:not([open])") && (!closed || element.tagName === "SUMMARY" && element.parentElement === closed);
        });
      const first = items[0], last = items.at(-1);
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", keyboard);
    return () => {
      document.removeEventListener("keydown", keyboard); document.body.style.overflow = overflow;
      siblings.forEach((element, index) => { element.inert = previousInert[index]; });
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  useEffect(() => { if (chat) { const frame = requestAnimationFrame(() => input.current?.focus({ preventScroll: true })); return () => cancelAnimationFrame(frame); } }, [chat]);

  async function send() {
    const text = draft.trim();
    if (!text || !onSend || sending || disabled || busy || chatAttachments.length) return;
    setSending(true); setSendError(""); following.current = true;
    if (chat) setDraft("");
    try { await onSend(text); if (!chat) setDraft(current => current.trim() === text ? "" : current); }
    catch (err) { if (chat) setDraft(current => current || text); setSendError(err instanceof Error ? err.message : "Your message could not be sent. Try again."); }
    finally { setSending(false); }
  }

  return <div ref={dialog} className={`app-shell fullscreen-voice theme-${theme} ${chat ? "is-chat-mode" : ""} ${hasConversation ? "has-voice-conversation" : "is-voice-welcome"} ${showText ? "" : "voice-captions-hidden"}`}
    data-phase={connecting ? "connecting" : mood} role="dialog" aria-modal="true" aria-labelledby="fullscreen-voice-title" tabIndex={-1}>
    <AmbientBackground />
    {overlay}
    <header className="fullscreen-voice-header">
      <div className="fullscreen-voice-identity"><span className="fullscreen-voice-mark" aria-hidden="true">d.</span><div><h1 id="fullscreen-voice-title">Darius <span>{chat ? "Creative chat" : "Live space"}</span></h1><p title={`${projectName} · ${sessionName}`}>{projectName}<span aria-hidden="true"> / </span>{sessionName}</p></div></div>
      <div className="fullscreen-voice-header-actions"><button type="button" className="icon-button" aria-label="Close fullscreen voice" title="Return to chat" onClick={onClose}><X size={20} /></button>{onSend ? <div className="segmented" aria-label="Fullscreen interaction"><button type="button" aria-pressed={chat} onClick={() => { setChat(true); if (phase !== "off") onStop(); }}>Chat</button><button type="button" aria-pressed={!chat} onClick={() => setChat(false)}>Voice</button></div> : null}<span className="fullscreen-voice-connection"><i aria-hidden="true" />{chat ? "Creative chat" : cloud ? "Cloud voice" : voiceBackend === "pipecat" ? "Pipecat · CPU" : "Classic voice"}</span></div>
    </header>
    {contextPanel ? <div className="fullscreen-context-host">{contextPanel}</div> : null}
    <div className="fullscreen-voice-presence">
      <div className="fullscreen-voice-orb"><LiquidOrb mood={mood} /></div>
      <div className="fullscreen-voice-presence-copy"><p className="fullscreen-voice-status" role="status">{status}</p><p className="fullscreen-voice-hint">{hasConversation ? "Your ideas, your creations, one conversation." : "A little space to think out loud."}</p></div>
    </div>
    <main className="fullscreen-voice-main">
      <div ref={scroller} className="fullscreen-voice-scroll" role="region" aria-label="Fullscreen conversation" tabIndex={0}
        onWheelCapture={() => { scrollIntentUntil.current = performance.now() + 1200; }}
        onTouchMoveCapture={() => { scrollIntentUntil.current = performance.now() + 1200; }}
        onPointerDown={(event) => { if (event.target === event.currentTarget) scrollIntentUntil.current = performance.now() + 1200; }}
        onKeyDown={(event) => { if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key)) scrollIntentUntil.current = performance.now() + 1200; }}
        onScroll={() => {
          const area = scroller.current;
          if (!area) return;
          const nearBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 96;
          // Image loading/layout anchoring may dispatch scroll events too. Only
          // a user gesture should detach the live edge from incoming content.
          if (nearBottom) following.current = true;
          else if (performance.now() < scrollIntentUntil.current) following.current = false;
          setShowLatest(!following.current);
        }} onLoadCapture={() => { if (following.current) latest(); }}>
        <div ref={content} className="fullscreen-voice-flow">
          {!hasConversation ? <div className="fullscreen-voice-welcome"><span className="eyebrow">Let’s make something</span><h2>Where shall we go?</h2><p>Talk through an idea, direct a scene, or ask Darius to create. Your conversation stays here as it unfolds.</p><div className="fullscreen-voice-suggestions"><span>Explore an idea</span><span>Bring a scene to life</span><span>Refine a creation</span></div></div> : null}
          {loading ? <p className="fullscreen-voice-empty" role="status">Opening your conversation…</p> : null}
          {history.map((message) => <article key={message.id} className={`fullscreen-voice-turn ${message.role === "user" ? "voice-turn-user" : "voice-turn-darius"}`} aria-label={`${message.role === "user" ? "You" : "Darius"} message`}>
            <span className="fullscreen-voice-speaker">{message.role === "user" ? "You" : "Darius"}</span>
            {showText ? <div className="fullscreen-voice-text">{renderText ? renderText(message) : <p>{message.content}</p>}</div> : null}
            {renderMessage ? <div className="fullscreen-voice-message-results">{renderMessage(message)}</div> : null}
          </article>)}
          {!history.length && reply && showText ? <article className="fullscreen-voice-turn voice-turn-darius"><span className="fullscreen-voice-speaker">Darius</span><p className="fullscreen-voice-text">{reply}</p></article> : null}
          {currentDraft && showText ? <article className="fullscreen-voice-turn voice-turn-user voice-turn-draft" aria-label="Your live transcript"><span className="fullscreen-voice-speaker">You · {waitingForReply ? "next message held" : transcribing ? "finalizing" : "live"}</span><p className="fullscreen-voice-text">{transcript}<span className="voice-text-cursor" aria-hidden="true" /></p></article> : null}
          {streamedReply && showText ? <article className="fullscreen-voice-turn voice-turn-darius voice-turn-streaming" aria-label="Darius reply in progress"><span className="fullscreen-voice-speaker">Darius · replying</span><p className="fullscreen-voice-text">{streamedReply}<span className="voice-text-cursor" aria-hidden="true" /></p></article> : null}
          {busy && !streamedReply ? <div className="fullscreen-voice-thinking" aria-label="Darius is working"><span /><span /><span /><small>Following your lead</small></div> : null}
          {!showText && hasConversation ? <p className="fullscreen-voice-empty">Captions hidden. Your conversation is still saved, and results stay visible.</p> : null}
          {actions ? <div className="fullscreen-voice-tasks">{actions}</div> : null}
          {error || sendError ? <p className="form-error" role="alert">{error || sendError}</p> : null}
        </div>
      </div>
      {showLatest ? <button type="button" className="secondary-button fullscreen-voice-latest" onClick={() => { following.current = true; latest(); }}><ArrowDown size={15} />Back to live</button> : null}
    </main>
    <footer className="fullscreen-voice-footer">
      {showComposer && chatAttachments.length ? <p className="fullscreen-attachment-notice" role="status">{chatAttachments.length} attachment(s) are staged in chat. <button className="text-button" type="button" onClick={onClose}>Return to chat to review and send</button></p> : null}
      {showComposer && onSend ? <form className="fullscreen-voice-compose" onSubmit={(event) => { event.preventDefault(); void send(); }}>
        <textarea ref={input} aria-label="Message Darius in fullscreen" placeholder="Add a thought…" value={draft} rows={2} maxLength={20000} disabled={disabled || (!chat && (sending || busy))} onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} />
        <button type="submit" className="primary-button" disabled={!draft.trim() || chatAttachments.length > 0 || sending || disabled || busy} aria-label="Send fullscreen message"><ArrowUp size={18} /></button>
      </form> : null}
      <div className="fullscreen-voice-controls">
        <div className="fullscreen-voice-control-group">{!chat ? <button type="button" className="icon-button" aria-label="Toggle captions" aria-pressed={captions} title="Captions" onClick={() => setCaptions((value) => !value)}><Captions size={20} /></button> : null}
          {onSend && !chat ? <button type="button" className="icon-button" aria-label="Type a message" aria-pressed={showComposer} title="Type a message" onClick={() => { if (chat) setChat(false); else setTyping((value) => !value); }}><Keyboard size={20} /></button> : null}
          {!cloud ? <button type="button" className="icon-button" aria-label={spoken ? "Mute spoken replies" : "Enable spoken replies"} aria-pressed={spoken} title="Spoken replies" onClick={() => setSpoken(!spoken)}>{spoken ? <Volume2 size={20} /> : <VolumeX size={20} />}</button> : null}</div>
        <button type="button" className="fullscreen-voice-microphone" disabled={connecting || (phase === "off" && (disabled || busy))} aria-label={phase === "off" ? "Start listening" : "Pause voice"} onClick={phase === "off" ? onStart : onStop}>{phase === "off" ? <Mic size={24} /> : <MicOff size={24} />}<span>{connecting ? "Connecting" : phase === "off" ? "Start listening" : "Pause voice"}</span></button>
        <div className="fullscreen-voice-control-group"><details className="fullscreen-voice-settings"><summary aria-label="Voice session settings" title="Voice session settings"><Settings2 size={20} /></summary><div className="fullscreen-voice-options"><label>Voice engine<select aria-label="Fullscreen voice engine" value={cloud ? "cloud" : voiceBackend} disabled={busy || connecting} onChange={(event) => { onEngineChange(event.target.value === "cloud"); if (event.target.value !== "cloud") onBackendChange?.(event.target.value as "pipecat" | "classic"); }}><option value="pipecat">Pipecat · CPU streaming</option><option value="classic">Classic local voice</option><option value="cloud">Cloud voice</option></select></label><small>{cloud ? "Cloud voice uses your OpenAI key and is billed." : voiceBackend === "pipecat" ? "CPU speech, smart pauses, and natural interruption. The selected Darius model still handles requests." : "Classic speech remains available as a fallback."}</small></div></details><button type="button" className="icon-button fullscreen-voice-end" aria-label="End voice session" title="End session" onClick={onEnd ?? onClose}><PhoneOff size={20} /></button></div>
      </div>
      <div className="fullscreen-voice-footer-note">{canInterrupt ? <button type="button" className="text-button" onClick={onStart}>Interrupt & speak</button> : <small>{chat ? "Enter to send · Shift+Enter for a new line" : waitingForReply ? "Your next message sends when the current reply finishes." : phase === "off" ? "Start listening whenever you’re ready." : "Listening resumes after each reply."}</small>}<small>Saved in chat · Esc to leave</small></div>
    </footer>
  </div>;
}
