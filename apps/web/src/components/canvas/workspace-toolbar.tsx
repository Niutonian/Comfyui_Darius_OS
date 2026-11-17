"use client";
import { useRef } from "react";
import { ArrowLeft, ChevronDown, Download, Hand, Layers3, Maximize, Minimize2, Minus, MousePointer2, PanelRightOpen, Plus, Redo2, Undo2 } from "lucide-react";
import { canvasProfiles, FIBO_DEV, H3_ANIMATE, MOSS, type CanvasProfile } from "@/lib/canvas-profile";
import type { CanvasContent } from "@/lib/canvas-document";
import type { MossBoard } from "@/lib/moss-workspace";
import { imageRecipes } from "../image-recipe-board";

export type WorkspaceToolbarProps = {
  projectName: string; boards: MossBoard[]; selectedId: string | null; search: string; archives: boolean; creating: boolean; hand: boolean;
  canUndo: boolean; canRedo: boolean; scale: number; panelExpanded: boolean; expanded: boolean;
  onSearch: (value: string) => void; onJump: (board: MossBoard) => void; onToggleArchives: () => void;
  onAdd: (profile: CanvasProfile, content?: CanvasContent) => void; onImportError: (message: string) => void; onPrepare: () => void;
  onHand: (hand: boolean) => void; onUndo: () => void; onRedo: () => void; onZoom: (factor: number) => void;
  onTogglePanel: () => void; onFitAll: () => void; onExit?: () => void; onToggleExpanded?: () => void;
};

export function WorkspaceToolbar(p: WorkspaceToolbarProps) {
  const importer = useRef<HTMLInputElement>(null);
  return <header className="moss-toolbar">
    <div className="moss-project-heading">{p.onExit ? <button className="icon-button" aria-label="Back to Library" onClick={p.onExit}><ArrowLeft size={17} /></button> : null}<span>{p.projectName} <small>/ Canvas</small></span></div>
    <div className="moss-navigation"><label><Layers3 size={15} /><input aria-label="Search boards" placeholder="Find a board…" value={p.search} onChange={e => p.onSearch(e.target.value)} /></label>
      <select aria-label="Jump to board" value={p.selectedId ?? ""} onChange={e => { const b = p.boards.find(b => b.id === e.target.value); if (b) p.onJump(b); }}><option value="">Jump to board…</option>{p.boards.map(b => <option key={b.id} value={b.id}>{b.name}{b.archived ? " · archived" : ""}</option>)}</select>
      <button className="text-button" onClick={p.onToggleArchives}>{p.archives ? "Show workspace" : "Archived"}</button></div>
    <div className="moss-toolbar-actions">
      <button className="secondary-button canvas-add-board" aria-label="Add MOSS board" disabled={p.creating} onClick={() => p.onAdd(MOSS)}><Plus size={16} /><span className="canvas-add-full">MOSS board</span><span className="canvas-add-short" aria-hidden="true">MOSS</span></button>
      <button className="secondary-button canvas-add-board" aria-label="Add FIBO board" disabled={p.creating} onClick={() => p.onAdd(FIBO_DEV)}><Plus size={16} /><span className="canvas-add-full">FIBO board</span><span className="canvas-add-short" aria-hidden="true">FIBO</span></button>
      <details className="image-recipe-add"><summary className="secondary-button canvas-add-board" aria-label="Add image board" aria-disabled={p.creating} onClick={e => { if (p.creating) e.preventDefault(); }}><Plus size={16} /><span className="canvas-add-full">Image board</span><span className="canvas-add-short" aria-hidden="true">Image</span><ChevronDown size={12} className="canvas-add-chevron" /></summary>
        <div>{imageRecipes.map(profile => <button type="button" key={profile} disabled={p.creating} onClick={e => { e.currentTarget.closest("details")!.open = false; p.onAdd(profile); }}>{canvasProfiles[profile].name}</button>)}</div></details>
      <button className="secondary-button canvas-add-board canvas-add-video" aria-label="Add video board" disabled={p.creating} onClick={() => p.onAdd(H3_ANIMATE)}><Plus size={16} /><span className="canvas-add-full">Video board</span><span className="canvas-add-short" aria-hidden="true">Video</span></button>
      <button className="icon-button" aria-label="Import Canvas as board" onClick={() => importer.current?.click()}><Download size={17} /></button>
      <input type="file" ref={importer} hidden accept="application/json,.json" onChange={async e => { const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; if (file.size > 256000) { p.onImportError("Canvas JSON is limited to 256 KB"); return; } try { p.onAdd(MOSS, JSON.parse(await file.text())); } catch (error) { p.onImportError(error instanceof Error ? error.message : "Canvas JSON could not be read"); } }} />
      <button className="text-button" disabled={!p.selectedId} onClick={p.onPrepare}>Prepare board</button>
      <button className="icon-button" aria-label="Select boards" aria-pressed={!p.hand} onClick={() => p.onHand(false)}><MousePointer2 size={17} /></button><button className="icon-button" aria-label="Pan workspace" aria-pressed={p.hand} onClick={() => p.onHand(true)}><Hand size={17} /></button>
      <button className="icon-button" aria-label="Undo workspace action" disabled={!p.canUndo} onClick={p.onUndo}><Undo2 size={17} /></button><button className="icon-button" aria-label="Redo workspace action" disabled={!p.canRedo} onClick={p.onRedo}><Redo2 size={17} /></button>
      <button className="icon-button" aria-label="Zoom out workspace" onClick={() => p.onZoom(1 / 1.2)}><Minus size={16} /></button><span>{Math.round(p.scale * 100)}%</span><button className="icon-button" aria-label="Zoom in workspace" onClick={() => p.onZoom(1.2)}><Plus size={16} /></button>
      <button className="icon-button" aria-label="Open Canvas utilities" aria-expanded={p.panelExpanded} onClick={p.onTogglePanel}><PanelRightOpen size={17} /></button>
      {p.onToggleExpanded ? <button className="icon-button" aria-label={p.expanded ? "Restore Canvas window" : "Expand Canvas workspace"} onClick={p.onToggleExpanded}>{p.expanded ? <Minimize2 size={17} /> : <Maximize size={17} />}</button> : null}
      <button className="icon-button" aria-label="Fit all boards" onClick={p.onFitAll}><Maximize size={17} /></button>
    </div>
  </header>;
}
