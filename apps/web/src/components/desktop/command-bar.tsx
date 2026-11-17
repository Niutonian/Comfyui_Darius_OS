"use client";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowRight, Frame, MessageCircle, Plus, Search, Sparkles, StickyNote } from "lucide-react";
import { desktopApps, type AppId } from "@/lib/desktop-apps";
import { desktopActions, parseCommand, runCommand } from "@/lib/desktop-commands";
import { appIcons, CanvasIcon } from "./icons";

type Item = { id: string; label: string; hint?: string; icon: ReactNode; run: () => string | null | void };

const matches = (label: string, query: string) => query.toLowerCase().split(/\s+/).filter(Boolean).every(word => label.toLowerCase().includes(word));

/**
 * Ctrl/⌘+K: open any app, jump to or generate a board, add a note, or send the text
 * straight to Darius. The same bounded commands Darius understands in chat and voice.
 */
export function CommandBar({ open, onClose, onDone, projectOpen }: { open: boolean; onClose: () => void; onDone: (message: string) => void; projectOpen: boolean }) {
  const [query, setQuery] = useState(""), [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null), list = useRef<HTMLDivElement>(null);
  useEffect(() => { if (!open) return; const frame = requestAnimationFrame(() => input.current?.focus()); return () => cancelAnimationFrame(frame); }, [open]);
  const items = useMemo(() => {
    if (!open) return [];
    const a = desktopActions(), boards = projectOpen ? a.boards?.() ?? [] : [];
    const out: Item[] = [];
    const command = query.trim() ? parseCommand(query, boards, a.selectedBoard?.() ?? null) : null;
    if (command) out.push({ id: "command", label: query.trim(), hint: "Do it", icon: <Sparkles size={16} />, run: () => runCommand(command) });
    if (projectOpen) out.push({ id: "canvas", label: "Show the canvas", hint: "Minimize all windows", icon: <CanvasIcon size={16} />, run: () => { a.showCanvas?.(); } });
    for (const app of Object.keys(desktopApps) as AppId[]) {
      if (!projectOpen && desktopApps[app].project) continue;
      const Icon = appIcons[app];
      out.push({ id: `app-${app}`, label: `Open ${desktopApps[app].title}`, hint: "App", icon: <Icon size={16} />, run: () => { a.openApp?.(app); } });
    }
    for (const board of boards) {
      out.push({ id: `open-${board.id}`, label: `Open ${board.name}`, hint: "Board", icon: <ArrowRight size={16} />, run: () => { a.openBoard?.(board.id); } });
      out.push({ id: `generate-${board.id}`, label: `Generate ${board.name}`, hint: "Board", icon: <Sparkles size={16} />, run: () => { a.generateBoard?.(board.id); } });
    }
    if (projectOpen) {
      out.push({ id: "note", label: "New sticky note", hint: "Canvas", icon: <StickyNote size={16} />, run: () => { a.newBoard?.("note"); } });
      out.push({ id: "frame", label: "New frame", hint: "Canvas", icon: <Frame size={16} />, run: () => { a.newBoard?.("frame"); } });
      for (const [kind, label] of [["moss", "MOSS"], ["fibo", "FIBO"], ["image", "image"], ["video", "video"]] as const)
        out.push({ id: `new-${kind}`, label: `New ${label} board`, hint: "Canvas", icon: <Plus size={16} />, run: () => { a.newBoard?.(kind); } });
    }
    const filtered = out.filter(item => item.id === "command" || !query.trim() || matches(item.label, query));
    if (query.trim() && projectOpen && a.ask) filtered.push({ id: "ask", label: `Ask Darius: ${query.trim()}`, hint: "Chat", icon: <MessageCircle size={16} />, run: () => { a.ask?.(query.trim()); } });
    return filtered.slice(0, 40);
  }, [open, query, projectOpen]);
  const current = Math.min(active, Math.max(0, items.length - 1));
  useEffect(() => { list.current?.querySelector<HTMLElement>(`[data-index="${current}"]`)?.scrollIntoView({ block: "nearest" }); }, [current]);
  if (!open) return null;
  function choose(item: Item | undefined) {
    if (!item) return;
    const message = item.run();
    setQuery(""); setActive(0); onClose();
    if (typeof message === "string") onDone(message);
  }
  return <div className="dk-command-scrim" onPointerDown={event => { if (event.target === event.currentTarget) { setQuery(""); onClose(); } }}>
    <div className="dk-command" role="dialog" aria-modal="true" aria-label="Command bar">
      <label className="dk-command-input"><Search size={18} /><input ref={input} role="combobox" aria-expanded="true" aria-controls="dk-command-list" aria-activedescendant={items[current] ? `dk-command-${items[current].id}` : undefined}
        aria-label="Search apps, boards and actions, or ask Darius" placeholder="Open the library, generate a board, or ask Darius…" value={query}
        onChange={event => { setQuery(event.target.value); setActive(0); }}
        onKeyDown={event => {
          if (event.key === "ArrowDown") { event.preventDefault(); setActive(Math.min(items.length - 1, current + 1)); }
          else if (event.key === "ArrowUp") { event.preventDefault(); setActive(Math.max(0, current - 1)); }
          else if (event.key === "Enter") { event.preventDefault(); choose(items[current]); }
          else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setQuery(""); onClose(); }
        }} /><kbd>Esc</kbd></label>
      <div className="dk-command-list" id="dk-command-list" role="listbox" ref={list} aria-label="Results">
        {items.map((item, index) => <button key={item.id} id={`dk-command-${item.id}`} data-index={index} type="button" role="option" aria-selected={index === current} onPointerMove={() => setActive(index)} onClick={() => choose(item)}>
          <span className="dk-command-icon">{item.icon}</span><span className="dk-command-label">{item.label}</span>{item.hint ? <small>{item.hint}</small> : null}
        </button>)}
        {!items.length ? <p className="dk-command-empty">Nothing matches. Open a project to ask Darius.</p> : null}
      </div>
      <footer><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> run</span><span><kbd>`</kbd> talk to Darius</span></footer>
    </div>
  </div>;
}
