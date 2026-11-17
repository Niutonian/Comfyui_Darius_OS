"use client";
import { useEffect, useRef, useState } from "react";
import { Archive, Download, Hand, Maximize, Minus, MousePointer2, Plus, Redo2, Search, Undo2, Wrench } from "lucide-react";
import { canvasProfiles, FIBO_DEV, H3_ANIMATE, MOSS, type CanvasProfile } from "@/lib/canvas-profile";
import type { CanvasContent } from "@/lib/canvas-document";
import type { MossBoard } from "@/lib/moss-workspace";
import { imageRecipes } from "../image-recipe-board";

export type ToolPillProps = {
  hand: boolean; canUndo: boolean; canRedo: boolean; scale: number; creating: boolean; canPrepare: boolean;
  onHand: (hand: boolean) => void; onUndo: () => void; onRedo: () => void; onZoom: (factor: number) => void; onFitAll: () => void;
  onAdd: (profile: CanvasProfile, content?: CanvasContent) => void; onImportError: (message: string) => void; onPrepare: () => void;
};

/** The floating bottom bar of the canvas desktop. The dark "+" adds a board. */
export function ToolPill(p: ToolPillProps) {
  const [menu, setMenu] = useState(false);
  const importer = useRef<HTMLInputElement>(null), root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return;
    const away = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setMenu(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { event.stopPropagation(); setMenu(false); } };
    document.addEventListener("pointerdown", away); document.addEventListener("keydown", escape, true);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", escape, true); };
  }, [menu]);
  const add = (profile: CanvasProfile) => { setMenu(false); p.onAdd(profile); };
  return <div className="dk-tool-pill" ref={root} role="toolbar" aria-label="Canvas tools">
    <button type="button" aria-label="Select boards" title="Select (V)" aria-pressed={!p.hand} onClick={() => p.onHand(false)}><MousePointer2 size={17} /></button>
    <button type="button" aria-label="Pan workspace" title="Pan (H, or hold Space)" aria-pressed={p.hand} onClick={() => p.onHand(true)}><Hand size={17} /></button>
    <i aria-hidden="true" />
    <button type="button" aria-label="Undo workspace action" title="Undo (Ctrl+Z)" disabled={!p.canUndo} onClick={p.onUndo}><Undo2 size={17} /></button>
    <button type="button" aria-label="Redo workspace action" title="Redo (Ctrl+Shift+Z)" disabled={!p.canRedo} onClick={p.onRedo}><Redo2 size={17} /></button>
    <i aria-hidden="true" />
    <button type="button" aria-label="Zoom out workspace" onClick={() => p.onZoom(1 / 1.2)}><Minus size={16} /></button>
    <span className="dk-tool-zoom">{Math.round(p.scale * 100)}%</span>
    <button type="button" aria-label="Zoom in workspace" onClick={() => p.onZoom(1.2)}><Plus size={16} /></button>
    <button type="button" aria-label="Fit all boards" title="Fit all boards" onClick={p.onFitAll}><Maximize size={16} /></button>
    <button type="button" className="dk-tool-add" aria-label="Add a board" aria-haspopup="menu" aria-expanded={menu} disabled={p.creating} onClick={() => setMenu(open => !open)}><Plus size={19} /></button>
    {menu ? <div className="dk-tool-menu" role="menu" aria-label="Add a board">
      <span className="dk-menu-label">Composition</span>
      <button type="button" role="menuitem" aria-label="Add MOSS board" onClick={() => add(MOSS)}>MOSS board<small>Regions → one composition</small></button>
      <button type="button" role="menuitem" aria-label="Add FIBO board" onClick={() => add(FIBO_DEV)}>FIBO board<small>Regions with palettes</small></button>
      <span className="dk-menu-label">Image</span>
      {imageRecipes.map(profile => <button type="button" role="menuitem" key={profile} onClick={() => add(profile)}>{canvasProfiles[profile].name}<small>{canvasProfiles[profile].action}</small></button>)}
      <span className="dk-menu-label">Video</span>
      <button type="button" role="menuitem" aria-label="Add video board" onClick={() => add(H3_ANIMATE)}>Video board<small>MiniMax H3</small></button>
      <i aria-hidden="true" />
      <button type="button" role="menuitem" aria-label="Import Canvas as board" onClick={() => { setMenu(false); importer.current?.click(); }}><Download size={14} />Import Canvas JSON</button>
      <button type="button" role="menuitem" disabled={!p.canPrepare} onClick={() => { setMenu(false); p.onPrepare(); }}><Wrench size={14} />Prepare selected board</button>
    </div> : null}
    <input type="file" ref={importer} hidden accept="application/json,.json" onChange={async e => { const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; if (file.size > 256000) { p.onImportError("Canvas JSON is limited to 256 KB"); return; } try { p.onAdd(MOSS, JSON.parse(await file.text())); } catch (error) { p.onImportError(error instanceof Error ? error.message : "Canvas JSON could not be read"); } }} />
  </div>;
}

/** Top-centre finder: search, jump and the archive. */
export function BoardFinder({ boards, selectedId, search, archives, onSearch, onJump, onToggleArchives }: {
  boards: MossBoard[]; selectedId: string | null; search: string; archives: boolean;
  onSearch: (value: string) => void; onJump: (board: MossBoard) => void; onToggleArchives: () => void;
}) {
  return <div className="dk-finder" role="search">
    <label><Search size={15} /><input aria-label="Search boards" placeholder="Find a board…" value={search} onChange={e => onSearch(e.target.value)} /></label>
    <select aria-label="Jump to board" value={selectedId ?? ""} onChange={e => { const b = boards.find(b => b.id === e.target.value); if (b) onJump(b); }}><option value="">Jump to…</option>{boards.map(b => <option key={b.id} value={b.id}>{b.name}{b.archived ? " · archived" : ""}</option>)}</select>
    <button type="button" aria-pressed={archives} title={archives ? "Back to the workspace" : "Show archived boards"} onClick={onToggleArchives}><Archive size={15} /><span>{archives ? "Workspace" : "Archived"}</span></button>
  </div>;
}
