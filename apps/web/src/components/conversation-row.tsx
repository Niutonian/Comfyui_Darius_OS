"use client";

import { useState } from "react";
import { MessageSquarePlus, Pencil, Trash2 } from "lucide-react";
import type { Conversation } from "@/lib/types";

export function ConversationRow({ thread, active, disabled, onOpen, onRename, onDelete, onError }: {
  thread: Conversation; active: boolean; disabled: boolean;
  onOpen: () => void; onRename: (title: string) => Promise<void>; onDelete: () => Promise<void>; onError: (message: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [title, setTitle] = useState(thread.title);
  const [saving, setSaving] = useState(false);
  async function run(action: () => Promise<void>) {
    setSaving(true);
    try { await action(); setEditing(false); setConfirming(false); }
    catch (error) { onError(error instanceof Error ? error.message : "Could not update this chat."); }
    finally { setSaving(false); }
  }
  return <div className="conversation-row">
    <button className={`talk-thread ${active ? "active" : ""}`} disabled={disabled || saving} onClick={onOpen} type="button"><MessageSquarePlus size={14} aria-hidden="true" /><small>{thread.title}</small><time dateTime={thread.updated_at}>{thread.updated_at ? new Date(thread.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}</time></button>
    <button className="secondary-button" disabled={disabled || saving} aria-label={`Rename chat ${thread.title}`} title="Rename chat" onClick={() => { setTitle(thread.title); setEditing(true); setConfirming(false); }} type="button"><Pencil size={14} /></button>
    <button className="secondary-button" disabled={disabled || saving} aria-label={`Delete chat ${thread.title}`} title="Delete chat" onClick={() => { setConfirming(true); setEditing(false); }} type="button"><Trash2 size={14} /></button>
    {editing ? <form className="conversation-row-editor" onSubmit={(event) => { event.preventDefault(); if (title.trim()) void run(() => onRename(title.trim())); }}>
      <label>Chat name<input autoFocus maxLength={300} value={title} onChange={(event) => setTitle(event.target.value)} disabled={saving} /></label>
      <button className="primary-button" disabled={disabled || saving || !title.trim()} type="submit">Save name</button>
      <button className="secondary-button" disabled={saving} onClick={() => setEditing(false)} type="button">Cancel</button>
    </form> : null}
    {confirming ? <div className="conversation-row-editor"><p>Delete “{thread.title}” and its messages permanently? Assets and render jobs are kept.</p><button className="secondary-button" disabled={disabled || saving} onClick={() => void run(onDelete)} type="button">Confirm delete</button><button className="secondary-button" disabled={saving} onClick={() => setConfirming(false)} type="button">Cancel</button></div> : null}
  </div>;
}
