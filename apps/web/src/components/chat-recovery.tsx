"use client";
import type { Message } from "@/lib/types";
import { useDariusStore } from "@/lib/store";

export function ChatRecovery({ message, busy, onRetry }: { message: Message; busy: boolean; onRetry: (message: Message) => void }) {
  const value = message.metadata.recovery;
  if (!value || typeof value !== "object") return null;
  const recovery = value as { action?: string; label?: string; can_retry?: boolean; detail?: string };
  return <div className="assistant-result-status has-failure" aria-label="Generation needs attention">
    <strong>Needs attention · request saved</strong>
    <small>Your prompt and references are kept. No automatic retry will run.</small>
    {recovery.action === "clarify" ? <small>Reply in chat with the missing detail or attach the image you mean.</small> : null}
    {recovery.action === "workflows" ? <button className="secondary-button" type="button" onClick={() => useDariusStore.getState().setView("create")}>Open trusted workflows</button> : null}
    {recovery.action === "settings" ? <button className="secondary-button" type="button" onClick={() => useDariusStore.getState().setView("settings")}>Open settings</button> : null}
    {recovery.action === "jobs" ? <button className="secondary-button" type="button" onClick={() => useDariusStore.getState().setTrayOpen(true)}>Check existing renders</button> : null}
    {recovery.can_retry === true ? <button className="secondary-button" type="button" disabled={busy} onClick={() => onRetry(message)}>Retry saved request</button> : null}
  </div>;
}
