"use client";
import { useState } from "react";
import { ArrowUp, X } from "lucide-react";
import type { Asset } from "@/lib/types";
import { assetName } from "@/lib/chat-labels";

export type ResultAction = "edit" | "animate" | "upscale";
export type ResultFollowupDraft = { id: number; asset: Asset; action: ResultAction };

export function ResultFollowup({ draft, busy, onSend, onClose }: { draft: ResultFollowupDraft; busy: boolean; onSend: (text: string, asset: Asset) => Promise<unknown>; onClose: () => void }) {
  const defaults = { edit: `Edit this ${draft.asset.kind}: `, animate: "Animate this image with a subtle cinematic camera move, preserving the subject.", upscale: "Upscale this image 2x, preserving its subject and composition." };
  const [text, setText] = useState(defaults[draft.action]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  async function send() {
    if (busy || sending || !text.trim() || (draft.action === "edit" && text.trim() === defaults.edit.trim())) return;
    setSending(true); setError("");
    try { await onSend(text, draft.asset); onClose(); }
    catch (err) { setError(err instanceof Error ? err.message : "The follow-up could not be sent. Your draft is kept."); }
    finally { setSending(false); }
  }
  return <form className="result-followup" aria-label="Result follow-up draft" onSubmit={event => { event.preventDefault(); void send(); }}>
    <header><div><span className="eyebrow">{draft.action === "edit" ? "Refine" : draft.action === "animate" ? "Bring to life" : "More detail"}</span><strong>{assetName(draft.asset)}</strong></div><button className="icon-button" type="button" aria-label="Close result follow-up" disabled={sending} onClick={onClose}><X size={16} /></button></header>
    <label>Your instruction<textarea aria-label="Result follow-up instruction" rows={3} maxLength={20000} value={text} disabled={sending || busy} onChange={event => setText(event.target.value)} /></label>
    <small>Uses only this {draft.asset.kind} and the trusted defaults for this action, not the previous render’s workflow. Your saved focus and other selected references stay unchanged. Nothing starts until you send; normal approval rules apply.</small>
    {error ? <p role="alert" className="form-error">{error}</p> : null}
    <button className="primary-button" type="submit" disabled={busy || sending || !text.trim() || (draft.action === "edit" && text.trim() === defaults.edit.trim())}><ArrowUp size={15} />{sending ? "Sending…" : "Send follow-up"}</button>
  </form>;
}
