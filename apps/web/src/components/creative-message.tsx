"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Copy, Layers3, Undo2, X } from "lucide-react";
import type { Message } from "@/lib/types";
import type { DariusMood } from "@/lib/types";
import { LiquidOrb } from "./liquid-orb";
import { mossApi, type ProjectWorkspace } from "@/lib/moss-workspace";
import { acceptPromptReceipt, assertCleanBoard, openPromptBoard, promptApi, type PromptApply, type PromptReceipt, type PromptSource, type PromptTarget } from "@/lib/prompt-transfer";
import { useDariusStore } from "@/lib/store";
import { SaveIdea } from "./creative-ideas";

type Draft = { id: string; title: string; text: string };
export function CreativeChatWelcome({ mood }: { mood: DariusMood }) {
  return <div className="creative-chat-welcome"><LiquidOrb mood={mood} /><h2>Room for your next idea.</h2><p>Develop a concept, explore a story, or write a prompt together.<br />Use in board takes a finished prompt to Canvas.</p></div>;
}
function draftsFor(message: Message): Draft[] {
  const raw = message.metadata.prompt_drafts;
  if (!Array.isArray(raw)) return [];
  return raw.filter((d): d is Draft => d && typeof d.id === "string" && typeof d.title === "string" && typeof d.text === "string" && d.text.length > 0 && d.text.length <= 30000).slice(0, 12);
}

export function CreativeMessage({ message, projectId }: { message: Message; projectId: string }) {
  const root = useRef<HTMLDivElement>(null), [source, setSource] = useState<PromptSource | null>(null), [notice, setNotice] = useState("");
  const drafts = draftsFor(message);
  function snapshot(text = message.content, draft?: Draft) {
    if (!draft) {
      const selection = window.getSelection();
      if (selection && root.current?.contains(selection.anchorNode) && root.current?.contains(selection.focusNode) && selection.toString().trim()) text = selection.toString();
    }
    return { messageId: message.id, draftId: draft?.id, title: draft?.title ?? "Selected reply text", text };
  }
  async function copy(text: string) { try { await navigator.clipboard.writeText(text); setNotice("Copied"); } catch { setNotice("Select the text and use your device’s Copy action."); } }
  const parts: React.ReactNode[] = []; let offset = 0;
  for (const draft of drafts) {
    const pattern = /^```prompt(?:[ \t]+[^\r\n]{0,120})?[ \t]*\r?\n([\s\S]*?)\r?\n```[ \t]*(?=\r?$)/gm;
    const match = [...message.content.matchAll(pattern)].find(m => m.index! >= offset && m[1] === draft.text);
    if (!match) continue;
    parts.push(<p key={`text-${draft.id}`}>{message.content.slice(offset, match.index)}</p>);
    parts.push(<section className="creative-prompt-card" key={draft.id} aria-label={`Prompt draft: ${draft.title}`}><small>Prompt draft</small><strong>{draft.title}</strong><div className="creative-prompt-text">{draft.text}</div><div className="creative-prompt-actions"><button type="button" className="secondary-button" onClick={() => void copy(draft.text)}><Copy size={14} />Copy</button><button type="button" className="secondary-button" onClick={() => setSource(snapshot(draft.text, draft))}><Layers3 size={14} />Use in board</button><SaveIdea projectId={projectId} messageId={message.id} text={draft.text}/></div></section>);
    offset = match.index! + match[0].length;
  }
  parts.push(<p key="last">{message.content.slice(offset)}</p>);
  return <div ref={root} className="creative-message">{parts}<div className="creative-reply-actions"><SaveIdea projectId={projectId} messageId={message.id} text={message.content}/><button type="button" className="text-button" onPointerDown={e => e.preventDefault()} onClick={() => setSource(snapshot())}>Use selected text or reply in board</button><button type="button" className="text-button" onClick={() => void copy(message.content)}>Copy reply</button>{notice ? <small role="status">{notice}</small> : null}</div>{source ? <PromptTransfer key={`${projectId}:${message.id}`} projectId={projectId} source={source} onClose={() => setSource(null)} /> : null}</div>;
}

export function PromptTransfer({ projectId, source, onClose }: { projectId: string; source: PromptSource; onClose: () => void }) {
  const client = useQueryClient(), dialog = useRef<HTMLDialogElement>(null), heading = useId();
  const [boardId, setBoardId] = useState(""), [target, setTarget] = useState<PromptTarget | null>(null), [candidate, setCandidate] = useState(source.text), [busy, setBusy] = useState(false), [error, setError] = useState(""), [receipt, setReceipt] = useState<PromptReceipt | null>(null), [reviewing, setReviewing] = useState(false);
  const lastRequest = useRef<PromptApply | null>(null), chosen = useRef("");
  const workspace = useQuery({ queryKey: ["moss-workspace", projectId], queryFn: () => mossApi.get(projectId) });
  const boards = workspace.data?.boards.filter(b => !b.archived) ?? [];
  useEffect(() => { const node = dialog.current, previous = document.activeElement as HTMLElement | null; node?.showModal(); return () => { node?.close(); previous?.focus?.(); }; }, []);
  async function review(id: string) {
    chosen.current = id; setBoardId(id); setTarget(null); setError(""); setReviewing(true); lastRequest.current = null;
    try { const value = await promptApi.review(projectId, id); if (chosen.current === id) setTarget(value); }
    catch (err) { if (chosen.current === id) setError((err as Error).message); }
    finally { if (chosen.current === id) setReviewing(false); }
  }
  function received(value: PromptReceipt, updateDrafts = true) {
    if (updateDrafts) acceptPromptReceipt(projectId, value);
    client.setQueryData<ProjectWorkspace>(["moss-workspace", projectId], old => old ? { ...old, boards: old.boards.map(b => b.id === value.board.id ? value.board : b) } : old);
    client.setQueryData(["canvas", projectId, value.board.documentId], value.document);
    void client.invalidateQueries({ queryKey: ["moss-workspace", projectId] });
    setReceipt(value);
  }
  async function apply() {
    if (!target || busy) return;
    setBusy(true); setError("");
    try {
      const board = workspace.data?.boards.find(b => b.id === target.boardId); if (!board) throw new Error("This board is unavailable. Refresh the list.");
      assertCleanBoard(projectId, board);
      const snapshot = { sourceMessageId:source.messageId, sourceDraftId:source.draftId, sourceText:source.text, text:candidate, boardRevision:target.boardRevision, documentRevision:target.documentRevision, destination:target.destination.key };
      const old = lastRequest.current;
      const payload = old && JSON.stringify({ ...old, transferId:undefined }) === JSON.stringify(snapshot) ? old : { ...snapshot, transferId:crypto.randomUUID() };
      lastRequest.current = payload;
      const result = await promptApi.apply(projectId, target.boardId, payload);
      // If a local edit happened during the network call, leave it intact.
      let clean = true;
      try { assertCleanBoard(projectId, board); } catch { clean = false; }
      received(result, clean);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function undo() {
    if (!receipt || busy) return; setBusy(true); setError("");
    try { const board=workspace.data?.boards.find(b=>b.id===receipt.board.id); if(board)assertCleanBoard(projectId,board); received(await promptApi.undo(projectId, receipt.board.id, receipt.transferId)); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  function open(board?: string) { if (useDariusStore.getState().activeProjectId !== projectId) return; openPromptBoard(projectId, board); useDariusStore.getState().setView("create"); onClose(); }
  return createPortal(<dialog ref={dialog} className="prompt-transfer" aria-labelledby={heading} onKeyDown={e => e.stopPropagation()} onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}><header><div><small>From your conversation</small><h2 id={heading}>Use in board</h2></div><button type="button" className="icon-button" aria-label="Close prompt transfer" disabled={busy} onClick={onClose}><X size={19} /></button></header><div className="prompt-transfer-body">{receipt ? <><p role="status">{receipt.undone ? "Prompt transfer undone" : `Prompt added to ${receipt.board.name}`}</p><p>Your board’s Generate button starts the render.</p><div className="creative-prompt-actions"><button type="button" className="primary-button" onClick={() => open(receipt.board.id)}><ArrowUpRight size={15} />Open board</button>{!receipt.undone ? <button type="button" className="secondary-button" disabled={busy} onClick={() => void undo()}><Undo2 size={15} />Undo</button> : null}</div></> : <><p>Choose a destination and review the exact text. Applying updates only its prompt.</p>{workspace.isPending ? <p role="status">Loading boards…</p> : workspace.isError ? <p role="alert">Could not load boards. <button type="button" onClick={() => void workspace.refetch()}>Retry</button></p> : !boards.length ? <div><p>No available boards in this project. Your prompt is kept here to copy.</p><button type="button" className="secondary-button" onClick={() => open()}>Open Canvas to add a board</button></div> : <label>Destination board<select aria-label="Destination board" value={boardId} disabled={busy} onChange={e => void review(e.target.value)}><option value="" disabled>Choose a board…</option>{boards.map(b => <option key={b.id} value={b.id}>{b.name} · {b.kind === "minimax-h3-video" ? `H3 ${b.settings.video?.activeMode}` : b.kind === "image-recipe" ? b.settings.image?.activeProfile : b.kind === "fibo-t2i" ? "FIBO" : "MOSS"}</option>)}</select></label>}{reviewing ? <p role="status">Checking prompt destination…</p> : null}{target ? <div className="prompt-destination"><strong>{target.name} / {target.destination.label}</strong>{target.text ? <details><summary>Existing prompt · will be replaced</summary><p>{target.text}</p></details> : <small>This prompt field is empty.</small>}</div> : null}<label>Prompt to apply<textarea aria-label="Prompt to apply" rows={9} value={candidate} disabled={busy} onChange={e => setCandidate(e.target.value)} /></label>{target ? <small>{candidate.length.toLocaleString()} / {target.destination.maxLength.toLocaleString()} characters</small> : null}<div className="creative-prompt-actions"><button type="button" className="secondary-button" onClick={() => void navigator.clipboard.writeText(candidate).catch(() => setError("Select the prompt text and use Copy on your device."))}><Copy size={14} />Copy</button><button type="button" className="primary-button" disabled={!target || target.archived || busy || !candidate.trim() || candidate.length > target.destination.maxLength} onClick={() => void apply()}>{busy ? "Applying…" : target?.text ? "Replace prompt" : "Apply prompt"}</button></div></>}{error ? <div role="alert"><p>{error}</p>{!receipt && boardId ? <button type="button" className="secondary-button" disabled={busy} onClick={() => void review(boardId)}>Refresh target review</button> : null}</div> : null}</div></dialog>, document.body);
}
