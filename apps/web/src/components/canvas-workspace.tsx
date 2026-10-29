"use client";
/* eslint-disable @next/next/no-img-element -- stored local asset URLs */
import dynamic from "next/dynamic";
import { createPortal } from "react-dom";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowLeft, ArrowUp, Check, ChevronDown, ChevronRight, Copy, Download, Eye, EyeOff, Focus, Hand, History, Layers3, LockKeyhole, Maximize, Minus, MousePointer2, Plus, Redo2, Save, Scan, Sparkles, Trash2, Undo2, UnlockKeyhole, X } from "lucide-react";
import { ApiError, API_BASE } from "@/lib/api-client";
import { definitiveGenerationError, canvasApi, type CanvasDocument } from "@/lib/canvas-api";
import { commit, descendants, duplicateRegion, emptyCanvas, localRect, parentRect, redo, removeRegion, reparentRegion, reorderRegion, resolveRegions, sameContent, undo, updateRect, type CanvasContent, type CanvasHistory, type CanvasRegion, type CanvasViewport, type Rect, type RegionKind } from "@/lib/canvas-document";
import { useWorkspaceState } from "@/lib/workspace-session";
import { useDariusStore } from "@/lib/store";
import { subscribeProjectRefresh } from "@/lib/project-sync";
import type { Asset } from "@/lib/types";
import type { CanvasTool } from "./canvas-stage";
import { CanvasProfileControls, CanvasGenerationDetails } from "./canvas-profile-controls";
import { canvasProfiles, MOSS, type CanvasProfile } from "@/lib/canvas-profile";
import { registerCanvasSaver, mossApi, type MossBoard } from "@/lib/moss-workspace";
import { loadCanvasIntent } from "@/lib/canvas-intent";
import { CanvasUtilityPanel, useCanvasNarrow } from "./canvas-utility-panel";

const CanvasStage = dynamic(() => import("./canvas-stage"), { ssr: false, loading: () => <div className="canvas-loading" role="status">Preparing your artboard…</div> });
export type CanvasHosts = { onComposerHost?: (host: HTMLDivElement | null) => void; onAssistantHost?: (host: HTMLDivElement | null) => void; assistantOpen?: boolean; onToggleAssistant?: () => void };
type Props = CanvasHosts & { projectId: string; assets: Asset[] };
type Draft = { history: CanvasHistory; revision: number; saved: CanvasContent; pending?: { revision: number; key: string; seed: number | string | null; profileId?: string; boardId?: string; boardRevision?: number } };
const message = (error: unknown) => error instanceof Error ? error.message : "Canvas could not complete that operation. Your draft is retained.";
const contentUrl = (asset: string) => `${API_BASE}/assets/${encodeURIComponent(asset)}/content`;
const fieldTarget = (target: EventTarget | null) => target instanceof HTMLElement && Boolean(target.closest("input, textarea, select, [contenteditable=true]"));

function exportDocument(content: CanvasContent) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(content, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = `${content.name.replace(/[^\p{L}\p{N} _-]/gu, "").trim() || "Canvas"}.darius-canvas.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function CanvasWorkspace(props: Props) {
  const client = useQueryClient();
  const [activeId, setActiveId] = useWorkspaceState<string | null>(`canvas:${props.projectId}:open`, null);
  const [error, setError] = useState(""), [creating, setCreating] = useState(false);
  const imports = useRef<HTMLInputElement>(null);
  const canvases = useQuery({ queryKey: ["canvases", props.projectId], queryFn: () => canvasApi.list(props.projectId), refetchInterval: 15000 });
  const engine = useQuery({ queryKey: ["canvas-engine"], queryFn: () => canvasApi.engine() });
  useEffect(() => subscribeProjectRefresh(props.projectId, change => {
    if (change.full || change.types.some(type => /^(canvas\.|generation\.|job\.)/.test(type))) {
      void client.invalidateQueries({ queryKey: ["canvases", props.projectId] });
      void client.invalidateQueries({ queryKey: ["canvas", props.projectId] });
    }
  }), [client, props.projectId]);
  useEffect(() => { if (!activeId && canvases.data?.length) setActiveId(canvases.data[0].id); }, [activeId, canvases.data, setActiveId]);
  async function create(content = emptyCanvas()) {
    setCreating(true); setError("");
    try { const doc = await canvasApi.create(props.projectId, content); client.setQueryData(["canvas", props.projectId, doc.id], doc); setActiveId(doc.id); await canvases.refetch(); }
    catch (error) { setError(message(error)); } finally { setCreating(false); }
  }
  const chooser = <div className="canvas-document-actions">
    <label><span className="sr-only">Saved canvases</span><select value={activeId ?? ""} onChange={event => setActiveId(event.target.value || null)}><option value="">Open saved canvas…</option>{canvases.data?.map(doc => <option key={doc.id} value={doc.id}>{doc.name}</option>)}</select></label>
    <button type="button" className="icon-button" aria-label="New canvas" title="New empty canvas" disabled={creating} onClick={() => void create()}><Plus size={17} /></button>
    <button type="button" className="icon-button" aria-label="Import Canvas document" title="Import Darius Canvas JSON" onClick={() => imports.current?.click()}><Download size={17} style={{ transform: "rotate(180deg)" }} /></button>
    <input ref={imports} hidden type="file" accept=".json,application/json" aria-label="Canvas document JSON" onChange={async event => {
      const file = event.target.files?.[0]; event.target.value = "";
      if (!file) return;
      if (file.size > 256000) { setError("Canvas JSON is limited to 256 KB"); return; }
      try { await create(JSON.parse(await file.text()) as CanvasContent); } catch (error) { setError(message(error)); }
    }} />
  </div>;
  return <section className="canvas-entry" aria-label="Darius Canvas">
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {canvases.isError ? <p role="alert">Saved canvases could not load. <button type="button" onClick={() => void canvases.refetch()}>Retry</button></p> : null}
    {activeId ? <CanvasEditor key={`${props.projectId}:${activeId}`} {...props} documentId={activeId} chooser={chooser} presets={engine.data?.presets ?? []} /> : <div className="canvas-first-run">
      {chooser}<span className="canvas-first-mark"><Scan size={42} strokeWidth={1.2} /></span><span className="eyebrow">Create / Canvas</span><h2>A little space for a bigger idea.</h2>
      <p>Arrange objects, characters and exact text. MOSS turns your layout into one composition, while your regions stay editable.</p>
      <button type="button" className="primary-button" disabled={creating} onClick={() => void create()}><Plus size={17} />New empty canvas</button>
      <small>No sample layout is loaded automatically. Generating redraws the whole image.</small>
    </div>}
  </section>;
}

export function CanvasEditor({ projectId, documentId, assets, chooser, presets, onComposerHost, onAssistantHost, assistantOpen, onToggleAssistant, onExit, board }: Props & { documentId: string; chooser: React.ReactNode; presets: { id: string; name: string; width: number; height: number }[]; onExit?: () => void; board?: MossBoard }) {
  const client = useQueryClient(), theme = useDariusStore(state => state.theme);
  const narrow = useCanvasNarrow();
  const query = useQuery({ queryKey: ["canvas", projectId, documentId], queryFn: () => canvasApi.get(projectId, documentId), refetchInterval: 2500, retry: 1 });
  const [draft, setStoredDraft] = useWorkspaceState<Draft | null>(`canvas:${projectId}:${documentId}:draft`, null);
  const [selected, setSelected] = useWorkspaceState<string | null>(`canvas:${projectId}:${documentId}:selected`, null);
  const [viewport, setViewport] = useWorkspaceState<CanvasViewport>(`canvas:${projectId}:${documentId}:viewport`, { x: 0, y: 0, scale: 0 });
  const [tool, setTool] = useState<CanvasTool>("select"), [kind, setKind] = useState<RegionKind>("object"), [drawParent, setDrawParent] = useState<string | null>(null);
  const [focus, setFocus] = useState(Boolean(onExit)), [layersOpen, setLayersOpen] = useState(false), [inspectorOpen, setInspectorOpen] = useState<boolean | null>(null), [historyOpen, setHistoryOpen] = useState(false);
  const exitFocus = () => { if (onExit) onExit(); else setFocus(false); };
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set()), [fitToken, setFitToken] = useState(0);
  const [size, setSize] = useState({ width: 600, height: 400 });
  const [showLayout, setShowLayout] = useState(true), [showResult, setShowResult] = useState(true), [before, setBefore] = useState(false), [compare, setCompare] = useState(false);
  const [error, setError] = useState(""), [warning, setWarning] = useState(""), [saving, setSaving] = useState(false), [preparingDocs, setPreparingDocs] = useWorkspaceState<Record<string, boolean>>(`canvas:${projectId}:preparing`, {}), [checking, setChecking] = useState(false), [engineStatus, setEngineStatus] = useState("");
  const generating = Boolean(preparingDocs[documentId]), setGenerating = (value: boolean) => setPreparingDocs(previous => ({ ...previous, [documentId]: value })); const [conflict, setConflict] = useState(false), [seed, setSeed] = useWorkspaceState<string>(`canvas:${documentId}:seed`, "");
  const root = useRef<HTMLDivElement>(null), current = useRef(draft), savePromise = useRef<Promise<CanvasDocument | undefined> | null>(null);
  // The workspace store updates synchronously. Keep async save/generate callbacks
  // on that same snapshot rather than waiting for React's next render.
  const setDraft = useCallback((next: Draft | null | ((previous: Draft | null) => Draft | null)) => {
    setStoredDraft(previous => {
      const value = typeof next === "function" ? next(previous) : next;
      current.current = value;
      return value;
    });
  }, [setStoredDraft]);
  useLayoutEffect(() => { current.current = draft; }, [draft]);
  const dirty = Boolean(draft && !sameContent(draft.history.present, draft.saved));
  const content = draft?.history.present;
  const resolved = content ? resolveRegions(content) : [];
  const selection = resolved.find(value => value.region.id === selected);
  const actualDrawParent = content?.regions.some(r => r.id === drawParent) ? drawParent : null;
  const results = query.data?.generations ?? [], active = results.find(result => result.id === query.data?.activeGenerationId);
  const previous = results.find(result => result.id === active?.provenance.promotedFromGenerationId) ?? results.find(result => result.status === "completed" && result.id !== active?.id);
  const profile: CanvasProfile = board?.settings.adapterVersion ?? MOSS;
  const profileInfo = canvasProfiles[profile];
  const availablePresets = presets;
  async function saveProfile(next: import("@/lib/moss-workspace").BoardSettings) { if (!board) return; await mossApi.save(projectId, board, next); await client.invalidateQueries({ queryKey: ["moss-workspace", projectId] }); }
  const displayed = compare && before ? previous : active;
  const imageAsset = displayed?.assetIds[0];
  const validImage = imageAsset && assets.some(asset => asset.id === imageAsset && asset.project_id === projectId);
  const busyResult = results.find(result => ["queued", "running", "cancelling"].includes(result.status));

  useEffect(() => {
    const remote = query.data;
    if (!remote) return;
    if (!current.current) { setDraft({ history: { past: [], present: remote.content, future: [] }, revision: remote.revision, saved: remote.content, pending: loadCanvasIntent(projectId, documentId) }); return; }
    if (remote.revision > current.current.revision) {
      if (sameContent(current.current.history.present, current.current.saved) && !savePromise.current) {
        setDraft({ history: { past: [], present: remote.content, future: [] }, revision: remote.revision, saved: remote.content });
      } else if (!savePromise.current) { setConflict(true); setError("This canvas changed on another device. Export your draft or reload the saved version; nothing was overwritten."); }
    }
  }, [query.data, setDraft, documentId, projectId]);

  const saveNow = useCallback(async (): Promise<CanvasDocument | undefined> => {
    if (savePromise.current) return savePromise.current;
    const state = current.current;
    if (!state || sameContent(state.history.present, state.saved)) return undefined;
    if (conflict) throw new Error("Resolve the other device's update before saving");
    const snapshot = state.history.present;
    setSaving(true);
    const work = canvasApi.save(projectId, documentId, state.revision, snapshot).then(remote => {
      setDraft(previous => previous ? { ...previous, revision: remote.revision, saved: snapshot } : previous);
      client.setQueryData(["canvas", projectId, documentId], remote);
      void client.invalidateQueries({ queryKey: ["canvases", projectId] });
      return remote;
    }).catch(error => { setError(message(error)); if (error instanceof ApiError && error.status === 409) setConflict(true); throw error; })
      .finally(() => { savePromise.current = null; setSaving(false); });
    savePromise.current = work;
    return work;
  }, [client, conflict, documentId, projectId, setDraft]);
  useEffect(() => { const remove = registerCanvasSaver(projectId, documentId, saveNow); return () => { remove(); void saveNow().catch(() => {}); }; }, [projectId, documentId, saveNow]);
  useEffect(() => {
    if (!dirty || saving || conflict) return;
    const timer = setTimeout(() => { void saveNow().catch(() => {}); }, 1000);
    return () => clearTimeout(timer);
  }, [dirty, saving, conflict, content, saveNow]);
  useEffect(() => {
    const prevent = (event: BeforeUnloadEvent) => { if (current.current && !sameContent(current.current.history.present, current.current.saved)) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", prevent); return () => window.removeEventListener("beforeunload", prevent);
  }, []);
  useEffect(() => {
    if (!focus || !root.current) return;
    const previousFocus = document.activeElement as HTMLElement | null, element = root.current;
    const siblings = Array.from(document.body.children).filter(node => node !== element && node instanceof HTMLElement) as HTMLElement[];
    const inert = siblings.map(node => node.inert); siblings.forEach(node => { node.inert = true; });
    element.focus();
    return () => { siblings.forEach((node, i) => { node.inert = inert[i]; }); previousFocus?.focus(); };
  }, [focus]);

  function edit(next: CanvasContent) {
    setError(""); setDraft(previous => previous ? { ...previous, history: commit(previous.history, next) } : previous);
  }
  function attempt(action: () => void) { try { action(); } catch (error) { setError(message(error)); } }
  function patchRegion(patch: Partial<CanvasRegion>) {
    if (!content || !selection) return;
    const ownUnlock = selection.region.locked && !resolved.find(v => v.region.id === selection.region.parentId)?.locked && Object.keys(patch).every(key => key === "locked");
    if (selection.locked && !ownUnlock) { setError("Unlock this region or its parent before editing"); return; }
    edit({ ...content, regions: content.regions.map(region => region.id === selected ? { ...region, ...patch } : region) });
  }
  function addRegion(rect: Rect, parentId: string | null) {
    if (!content) return;
    if (content.regions.length >= 64) { setError("Canvas supports up to 64 regions"); return; }
    const id = crypto.randomUUID(), local = localRect(rect, parentRect(content, parentId));
    edit({ ...content, regions: [...content.regions, { id, parentId, name: `${kind === "group" ? "Group" : kind === "text" ? "Text" : kind === "character" ? "Character" : "Object"} ${content.regions.length + 1}`,
      kind, ...local, order: content.regions.length, description: "", text: "", palette: [], visible: true, locked: false }] });
    setSelected(id); setTool("select"); setInspectorOpen(true);
  }
  async function generate() {
    if (!current.current || generating) return;
    setGenerating(true); setError("");
    try {
      let request = current.current.pending;
      if (!request) {
        const saved = await saveNow();
        const snapshot = current.current;
        if (!snapshot) return;
        if (!sameContent(snapshot.history.present, snapshot.saved)) throw new Error("The canvas changed while saving. Your latest edits are retained; press Generate composition again once saved.");
        if (!board && seed.trim() && (!/^\d+$/.test(seed) || Number(seed) >= 2**32)) throw new Error("Use a seed between 0 and 4,294,967,295 or leave it blank");
        request = { revision: saved?.revision ?? snapshot.revision, key: crypto.randomUUID(), seed: board ? board.settings.seed : seed.trim() ? Number(seed) : null, profileId: profile, ...(board ? { boardId: board.id, boardRevision: board.revision } : {}) };
        setDraft(previous => previous ? { ...previous, pending: request } : previous);
      }
      const receipt = await canvasApi.generate(projectId, documentId, request.revision, request.key, request.seed, request.boardId ? { boardId: request.boardId, boardRevision: request.boardRevision!, profileId: request.profileId } : board ? { boardId: board.id, boardRevision: board.revision } : undefined, () => setEngineStatus("Checking whether your job was queued..."));
      setDraft(previous => previous ? { ...previous, pending: undefined } : previous);
      if (receipt.launchError) setError(receipt.launchError);
      await query.refetch(); void client.invalidateQueries({ queryKey: ["jobs", { projectId }] });
    } catch (error) {
      setError(message(error));
      if (definitiveGenerationError(error)) setDraft(previous => previous ? { ...previous, pending: undefined } : previous);
    } finally { setGenerating(false); setEngineStatus(""); }
  }
  function keyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Tab" && focus && root.current) {
      const nodes = Array.from(root.current.querySelectorAll<HTMLElement>("button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex='0']")).filter(node => node.offsetParent !== null);
      const first = nodes[0], last = nodes.at(-1);
      if (event.shiftKey && (document.activeElement === first || document.activeElement === root.current)) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      return;
    }
    if (fieldTarget(event.target)) return;
    if (event.key === "Escape") { event.stopPropagation(); if (historyOpen || layersOpen || (inspectorOpen ?? !narrow) || assistantOpen) { setHistoryOpen(false); setLayersOpen(false); setInspectorOpen(false); if (assistantOpen) onToggleAssistant?.(); } else exitFocus(); return; }
    if (!content || !draft) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); setDraft({ ...draft, history: event.shiftKey ? redo(draft.history) : undo(draft.history) }); return; }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "d" && selected) { event.preventDefault(); attempt(() => { const copy = duplicateRegion(content, selected); edit(copy.content); setSelected(copy.selectedId); }); return; }
    if ((event.key === "Delete" || event.key === "Backspace") && selected) { event.preventDefault(); attempt(() => { edit(removeRegion(content, selected)); setSelected(null); }); return; }
    if (selection && event.key.startsWith("Arrow")) {
      event.preventDefault(); const step = event.shiftKey ? 10 : 1;
      edit(updateRect(content, selection.region.id, { ...selection.rect, x: selection.rect.x + (event.key === "ArrowRight" ? step : event.key === "ArrowLeft" ? -step : 0), y: selection.rect.y + (event.key === "ArrowDown" ? step : event.key === "ArrowUp" ? -step : 0) })); return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key.toLowerCase() === "v") setTool("select");
    if (event.key.toLowerCase() === "h") setTool("pan");
    if (event.key.toLowerCase() === "r") { setTool("draw"); setKind("object"); }
    if (event.key.toLowerCase() === "t") { setTool("draw"); setKind("text"); }
  }
  const onViewport = useCallback((value: CanvasViewport) => setViewport(value), [setViewport]);
  const onSize = useCallback((value: { width: number; height: number }) => setSize(value), []);
  if (!content || !draft) return <div className="canvas-loading" role={query.isError ? "alert" : "status"}>{query.isError ? <><p>{message(query.error)}</p><button type="button" onClick={() => void query.refetch()}>Retry opening canvas</button></> : "Opening your canvas…"}</div>;

  const rename = (name: string) => edit({ ...content, name });
  const zoom = (factor: number) => { const scale = Math.max(.08, Math.min(4, (viewport.scale || 1) * factor)); onViewport({ scale, x: size.width / 2 - (size.width / 2 - viewport.x) * scale / (viewport.scale || 1), y: size.height / 2 - (size.height / 2 - viewport.y) * scale / (viewport.scale || 1) }); };
  const ancestorIds = new Set<string>(); let ancestor = selection?.region.parentId; while (ancestor) { ancestorIds.add(ancestor); ancestor = content.regions.find(r => r.id === ancestor)?.parentId; }
  const hierarchy = <section className="canvas-layers" aria-label="Canvas layers"><header><strong>Layers</strong><span>{content.regions.length}</span></header>
        <button type="button" className={`canvas-layer-root ${selected === null ? "active" : ""}`} onClick={() => { setSelected(null); setInspectorOpen(true); }}> <Scan size={15} />Artboard</button>
        <div className="canvas-layer-list">{resolved.filter(value => {
          let id = value.region.parentId;
          while (id) { if (collapsed.has(id)) return false; id = content.regions.find(r => r.id === id)?.parentId ?? null; }
          return true;
        }).map(value => <div className={`canvas-layer ${selected === value.region.id ? "selected" : ""} ${value.hidden ? "hidden-region" : ""}`} key={value.region.id} style={{ "--depth": value.depth } as CSSProperties}>
          <button type="button" className="canvas-collapse" aria-label={`Toggle children of ${value.region.name}`} disabled={!content.regions.some(r => r.parentId === value.region.id)} onClick={() => setCollapsed(previous => { const next = new Set(previous); if (next.has(value.region.id)) next.delete(value.region.id); else next.add(value.region.id); return next; })}>{collapsed.has(value.region.id) ? <ChevronRight size={12} /> : <ChevronDown size={12} />}</button>
          <button type="button" className="canvas-layer-name" aria-label={`Select region ${value.region.name}`} onClick={() => { setSelected(value.region.id); setInspectorOpen(true); setLayersOpen(false); }}><span className={`canvas-kind kind-${value.region.kind}`}>{value.region.kind === "text" ? "T" : value.region.kind === "group" ? "▱" : value.region.kind === "character" ? "◉" : "□"}</span><span>{value.region.name}</span></button>
          <button type="button" aria-label={`${value.region.visible ? "Hide" : "Show"} ${value.region.name}`} disabled={value.locked} onClick={() => edit({ ...content, regions: content.regions.map(r => r.id === value.region.id ? { ...r, visible: !r.visible } : r) })}>{value.region.visible ? <Eye size={13} /> : <EyeOff size={13} />}</button>
          <button type="button" aria-label={`${value.region.locked ? "Unlock" : "Lock"} ${value.region.name}`} disabled={value.locked && !value.region.locked || Boolean(resolved.find(v => v.region.id === value.region.parentId)?.locked)} onClick={() => edit({ ...content, regions: content.regions.map(r => r.id === value.region.id ? { ...r, locked: !r.locked } : r) })}>{value.region.locked ? <LockKeyhole size={13} /> : <UnlockKeyhole size={13} />}</button>
        </div>)}</div>
        {!content.regions.length ? <p className="canvas-help">Draw a region to start. Groups organise the layout; they don’t produce separate images.</p> : null}
        <footer><button type="button" className="text-button" onClick={async () => { if (content.regions.length && !window.confirm("Replace this layout with the supplied example? You can undo this edit.")) return; try { const imported = await canvasApi.example(profile); edit(imported.content); setWarning(imported.warnings.join(" ")); setSelected(null); } catch (error) { setError(message(error)); } }}>Load supplied example</button></footer>
      </section>;
  const inspector = <section className="canvas-inspector" aria-label="Canvas region inspector">
        <header><div><span className="eyebrow">{selection ? selection.region.kind : "Whole composition"}</span><strong>{selection?.region.name ?? "Your artboard"}</strong></div></header>
        {selection ? <>
          <nav className="canvas-breadcrumbs" aria-label="Region ancestors"><button type="button" onClick={() => setSelected(null)}>Artboard</button>{resolved.filter(v => ancestorIds.has(v.region.id)).map(v => <button type="button" key={v.region.id} onClick={() => setSelected(v.region.id)}>{v.region.name}</button>)}</nav>
          <label>Name<input value={selection.region.name} maxLength={100} disabled={selection.locked} onChange={event => patchRegion({ name: event.target.value || "Region" })} /></label>
          <label>Kind<select value={selection.region.kind} disabled={selection.locked} onChange={event => patchRegion({ kind: event.target.value as RegionKind })}><option value="group">Group · structural only</option><option value="object">Object</option><option value="character">Character</option><option value="text">Text</option></select></label>
          <label>Describe this region<textarea value={selection.region.description} disabled={selection.locked} maxLength={2000} rows={4} placeholder={selection.region.kind === "text" ? "Appearance, font, colour…" : "What belongs in this region?"} onChange={event => patchRegion({ description: event.target.value })} /></label>
          {selection.region.kind === "text" ? <label>Exact text<textarea value={selection.region.text} disabled={selection.locked} maxLength={2000} rows={3} placeholder="Preserves your spelling and line breaks" onChange={event => patchRegion({ text: event.target.value })} /></label> : null}
          {profile !== MOSS ? <label>Palette · hex colours<input key={`${selection.region.id}:${selection.region.palette.join(",")}`} defaultValue={selection.region.palette.join(", ")} disabled={selection.locked} placeholder="#d4a574, #182a21" onBlur={e => { const palette = e.target.value.split(",").map(c => c.trim()).filter(Boolean); if (palette.length > 5 || palette.some(c => !/^#[0-9a-fA-F]{6}$/.test(c))) { setError("Use up to five six-digit hex colours"); return; } patchRegion({ palette }); }} /></label> : selection.region.palette.length ? <p className="form-error">This region has FIBO palette data. Choose FIBO or explicitly clear its palette before rendering with MOSS.</p> : null}
          <div className="canvas-geometry">{(["x", "y", "width", "height"] as const).map(key => <label key={key}>{key}<input type="number" aria-label={`Region ${key} in pixels`} step={1} min={key === "width" || key === "height" ? 1 : 0} value={Math.round(selection.rect[key])} disabled={selection.locked}
            onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value)) edit(updateRect(content, selection.region.id, { ...selection.rect, [key]: value })); }} /></label>)}</div>
          <label>Parent<select value={selection.region.parentId ?? ""} disabled={selection.locked} onChange={event => attempt(() => edit(reparentRegion(content, selection.region.id, event.target.value || null)))}><option value="">Artboard</option>{content.regions.filter(r => !descendants(content, selection.region.id).has(r.id)).map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
          <button type="button" className="secondary-button" disabled={selection.locked && !selection.region.locked || Boolean(resolved.find(v => v.region.id === selection.region.parentId)?.locked)} onClick={() => patchRegion({ locked: !selection.region.locked })}>{selection.locked ? <LockKeyhole size={14} /> : <UnlockKeyhole size={14} />}{selection.region.locked ? "Unlock document region" : "Lock document region"}</button>
          <small className="canvas-help">Locks prevent document edits. They do not protect generated pixels.</small>
          <div className="canvas-region-actions"><button type="button" className="icon-button" aria-label="Duplicate region" title="Duplicate (Ctrl+D)" onClick={() => attempt(() => { const copied = duplicateRegion(content, selection.region.id); edit(copied.content); setSelected(copied.selectedId); })}><Copy size={16} /></button>
            <button type="button" className="icon-button" aria-label="Move layer backward" disabled={selection.locked} onClick={() => attempt(() => edit(reorderRegion(content, selection.region.id, -1)))}><ArrowUp size={16} /></button>
            <button type="button" className="icon-button" aria-label="Move layer forward" disabled={selection.locked} onClick={() => attempt(() => edit(reorderRegion(content, selection.region.id, 1)))}><ArrowDown size={16} /></button>
            <button type="button" className="icon-button" aria-label="Delete region" disabled={selection.locked} onClick={() => attempt(() => { edit(removeRegion(content, selection.region.id)); setSelected(null); })}><Trash2 size={16} /></button></div>
        </> : null}
        <details className="canvas-composition-settings" open={!selection}><summary>Composition settings</summary>
          <label>Whole composition<textarea aria-label="Whole composition description" value={content.globalPrompt} maxLength={6000} rows={4} placeholder="Describe the overall scene, mood, medium and light…" onChange={event => edit({ ...content, globalPrompt: event.target.value })} /></label>
          <label>Artboard preset<select value={content.artboard.preset} onChange={event => { const preset = availablePresets.find(p => p.id === event.target.value); if (preset) edit({ ...content, artboard: { preset: preset.id, width: preset.width, height: preset.height } }); }}>{availablePresets.map(p => <option key={p.id} value={p.id}>{p.name} · {p.width} × {p.height}</option>)}</select></label>
          {board ? <CanvasProfileControls board={board} onChange={saveProfile} onError={setError} /> : <label>Seed<input aria-label="Composition seed" value={seed}  inputMode="numeric" placeholder="Randomise once per new generation" onChange={event => setSeed(event.target.value)} /></label>}
          {active ? <button type="button" className="text-button" onClick={() => { if (board) void saveProfile({ ...board.settings, seed: profile === MOSS ? Number(active.seed) : String(active.seed) }).catch(e => setError(message(e))); else setSeed(String(active.seed)); }}>Use displayed result’s seed</button> : null}
          <small className="canvas-help">{profileInfo.family} · 1 MP · {profileInfo.settings}. A fixed seed is not a pixel lock.</small>
          <button type="button" className="secondary-button" disabled={checking} onClick={async () => { setChecking(true); try { const report = await canvasApi.engine(true, profile); setEngineStatus(report.readiness?.ready ? "Installed nodes and model names are ready. No render was started." : report.readiness?.issues.join(" · ") || "Could not verify the engine"); } catch (error) { setEngineStatus(message(error)); } finally { setChecking(false); } }}>{checking ? "Checking…" : `Check ${profileInfo.family} engine`}</button>
          {engineStatus ? <p className="canvas-help" role="status">{engineStatus}</p> : null}
        </details>
        <details className="canvas-hierarchy" open={layersOpen} onToggle={event => setLayersOpen(event.currentTarget.open)}><summary>Hierarchy · {content.regions.length} regions</summary>{hierarchy}</details>
        <details className="canvas-shortcuts"><summary>Keyboard shortcuts</summary><p>V select · H pan · R region · T text<br />Arrows nudge · Shift + arrows 10 px<br />Ctrl/Cmd + Z undo · Shift + Z redo<br />Ctrl/Cmd + D duplicate · Delete remove<br />Wheel zoom · Shift + wheel pan</p></details>
      </section>;
  const versions = <section className="canvas-history" aria-label="Composition versions"><header><strong>Versions</strong></header>
        <div className="canvas-draft-entry"><Layers3 size={18} /><div><strong>Draft r{draft.revision}{dirty ? " · unsaved edits" : ""}</strong><small>Editable layout · not a generated image</small></div></div>
        {!results.length ? <p>Generations will appear here. Each version is one flattened composition, not a separate layer.</p> : null}
        {results.map(result => <div className="canvas-version" key={result.id}><button type="button" disabled={result.status !== "completed"} aria-pressed={result.id === active?.id} onClick={async () => { try { const next = await canvasApi.select(projectId, documentId, result.id); client.setQueryData(["canvas", projectId, documentId], next); setBefore(false); setCompare(false); } catch (error) { setError(message(error)); } }}>
          {result.assetIds[0] ? <img alt={`Composition from revision ${result.revision}`} src={contentUrl(result.assetIds[0])} /> : <span className="canvas-version-placeholder"><History size={22} /></span>}<span>Revision {result.revision}<small>{result.status} · seed {result.seed}</small></span>
        </button><CanvasGenerationDetails result={result} board={board} projectId={projectId} generations={results} onError={setError} />{result.error ? <p role="status">{result.error}</p> : null}{result.status === "queued" ? <button type="button" className="text-button" onClick={async () => { try { await canvasApi.start(projectId, documentId, result.id); await query.refetch(); } catch (error) { setError(message(error)); } }}>Start worker</button> : null}</div>)}
      </section>;
  const tools = <nav className="canvas-tools" aria-label="Canvas tools">
    {([["select", "Select (V)", MousePointer2], ["pan", "Pan (H)", Hand], ["draw", "Draw region (R)", Scan]] as const).map(([value, label, Icon]) => <button type="button" key={value} aria-label={label} title={label} aria-pressed={tool === value} onClick={() => setTool(value)}><Icon size={18} /></button>)}
    <label><span className="sr-only">New region type</span><select aria-label="New region type" value={kind} onChange={event => { setKind(event.target.value as RegionKind); setTool("draw"); }}><option value="object">Object</option><option value="character">Character</option><option value="text">Text</option><option value="group">Group</option></select></label>
    <i />
    <button type="button" aria-label="Undo canvas edit" title="Undo (Ctrl+Z)" disabled={!draft.history.past.length} onClick={() => setDraft({ ...draft, history: undo(draft.history) })}><Undo2 size={18} /></button>
    <button type="button" aria-label="Redo canvas edit" title="Redo (Ctrl+Shift+Z)" disabled={!draft.history.future.length} onClick={() => setDraft({ ...draft, history: redo(draft.history) })}><Redo2 size={18} /></button>
    <button type="button" aria-label="Toggle layers" title="Layers" aria-pressed={layersOpen} onClick={() => { setLayersOpen(value => !value); setInspectorOpen(true); setHistoryOpen(false); if (assistantOpen) onToggleAssistant?.(); }}><Layers3 size={18} /></button>
    <button type="button" aria-label="Toggle region inspector" title="Inspector" aria-pressed={Boolean(inspectorOpen ?? !narrow)} onClick={() => { setInspectorOpen(value => !(value ?? !narrow)); setHistoryOpen(false); if (assistantOpen) onToggleAssistant?.(); }}><Sparkles size={18} /></button>
    <button type="button" aria-label="Toggle generation history" title="Generation history" aria-pressed={historyOpen} onClick={() => { setHistoryOpen(value => !value); setInspectorOpen(true); if (assistantOpen) onToggleAssistant?.(); }}><History size={18} /></button>
  </nav>;
  const whole = <div className={`canvas-workspace canvas-editor-refined ${focus ? "is-focus app-shell os-desktop space-create theme-" + theme : ""} ${layersOpen ? "show-layers" : ""} ${(inspectorOpen ?? !narrow) ? "show-inspector" : ""}`} ref={root} tabIndex={0}
    role={focus ? "dialog" : "region"} aria-modal={focus || undefined} aria-label={focus ? "Canvas focus workspace" : "Canvas editor"} onKeyDown={keyboard}>
    <header className="canvas-header"><div className="canvas-heading">
      {focus ? <button type="button" className="icon-button" aria-label={onExit ? "Back to board workspace" : "Exit canvas focus"} onClick={exitFocus}><ArrowLeft size={18} /></button> : null}
      <div><span className="eyebrow">{onExit ? "Project / Workspace / Board" : focus ? "Darius / Canvas" : "Create / Canvas"}</span><input aria-label="Canvas name" value={content.name} maxLength={200} onChange={event => rename(event.target.value)} /></div>
      <span className={`canvas-save-state ${dirty ? "is-dirty" : ""}`} role="status" title={saving ? "Saving…" : dirty ? "Unsaved edits" : `Saved revision ${draft.revision}`}><Check size={13} />{saving ? "Saving" : dirty ? "Unsaved" : `Saved · r${draft.revision}`}</span>
    </div><div className="canvas-header-actions">
      {!focus ? chooser : null}
      <button type="button" className="icon-button" aria-label="Zoom out canvas" onClick={() => zoom(.8)}><Minus size={16} /></button><span className="canvas-zoom">{Math.round(viewport.scale * 100)}%</span><button type="button" className="icon-button" aria-label="Zoom in canvas" onClick={() => zoom(1.25)}><Plus size={16} /></button>
      <button type="button" className="icon-button" aria-label="Fit canvas to view" title="Fit artboard" onClick={() => setFitToken(value => value + 1)}><Maximize size={17} /></button>
      <button type="button" className="secondary-button canvas-export" onClick={() => exportDocument(content)}><Download size={15} /><span>Export</span></button>
      <button type="button" className="icon-button" aria-label={focus ? "Exit canvas focus mode" : "Enter canvas focus mode"} title={focus ? "Exit focus (Esc)" : "Focus mode"} onClick={() => focus ? exitFocus() : setFocus(true)}>{focus ? <X size={18} /> : <Focus size={18} />}</button>
      <button type="button" className="primary-button canvas-generate" disabled={generating || conflict || Boolean(busyResult)} onClick={() => void generate()}><Sparkles size={16} /><span>{generating ? "Preparing…" : busyResult ? busyResult.status === "queued" ? "Queued" : "Generating…" : draft.pending ? "Retry submission" : profileInfo.action}</span></button>
    </div></header>
    {error ? <div className="canvas-notice is-error" role="alert">{error}<button type="button" aria-label="Dismiss Canvas error" onClick={() => setError("")}><X size={14} /></button>
      {conflict ? <button type="button" onClick={() => { if (!window.confirm("Discard this local draft and load the saved version? Export first if you want to keep it.")) return; const remote = query.data; if (remote) { setDraft({ history: { past: [], present: remote.content, future: [] }, saved: remote.content, revision: remote.revision }); setConflict(false); setError(""); } }}>Reload saved version</button> : null}
    </div> : null}
    {warning ? <div className="canvas-notice" role="status">{warning}<button type="button" aria-label="Dismiss import warning" onClick={() => setWarning("")}><X size={14} /></button></div> : null}
    <div className="canvas-body">
      {tools}

      <div className="canvas-centre">

        <div className="canvas-view-options"><button type="button" aria-pressed={showLayout && (!showResult || !imageAsset)} onClick={() => { setShowLayout(true); setShowResult(false); }}>Layout</button><button type="button" aria-pressed={Boolean(imageAsset && showResult && !showLayout)} disabled={!imageAsset} onClick={() => { setShowLayout(false); setShowResult(true); }}>Result</button><button type="button" aria-pressed={Boolean(imageAsset && showLayout && showResult)} disabled={!imageAsset} onClick={() => { setShowLayout(true); setShowResult(true); }}>Overlay</button>
          <button type="button" aria-pressed={actualDrawParent === null} onClick={() => { setDrawParent(null); setTool("draw"); }}>Draw on artboard</button>
          <button type="button" aria-pressed={Boolean(actualDrawParent)} disabled={!selection || selection.locked} onClick={() => { setDrawParent(selected); setTool("draw"); }}>Draw inside selection</button>
          {active && previous ? <button type="button" aria-pressed={compare} onClick={() => { setCompare(value => !value); setBefore(false); }}>{active.provenance.promotedFromGenerationId ? "Compare with preview" : "Compare versions"}</button> : null}
          {compare && previous ? <><button type="button" aria-pressed={before} onClick={() => setBefore(true)}>{active?.provenance.promotedFromGenerationId ? "Preview" : "Before"} · r{previous.revision}</button><button type="button" aria-pressed={!before} onClick={() => setBefore(false)}>{active?.provenance.promotedFromGenerationId ? "Dev" : "After"} · r{active?.revision}</button></> : null}
        </div>
        <CanvasStage content={content} selectedId={selected} tool={tool} drawParent={actualDrawParent} viewport={viewport} onViewport={onViewport} fitToken={fitToken}
          onSelect={id => { setSelected(id); if (id) { setInspectorOpen(true); setHistoryOpen(false); if (assistantOpen) onToggleAssistant?.(); } }} onRect={(id, rect) => attempt(() => edit(updateRect(content, id, rect)))} onDraw={addRegion} onError={setError}
          imageUrl={validImage ? contentUrl(imageAsset) : undefined} showLayout={showLayout} showResult={showResult} onSize={onSize} />
        {displayed ? <details className="canvas-result-caption canvas-provenance"><summary>Showing result r{displayed.revision} · Layout r{draft.revision}{dirty ? " + unsaved edits" : displayed.revision !== draft.revision ? " has newer edits" : ""}</summary><p>Region guides edit the layout, not rendered pixels. {profileInfo.family} regenerates the whole composition. Seed {displayed.seed}.</p></details> : null}
      </div>



      <CanvasUtilityPanel open={historyOpen || (inspectorOpen ?? !narrow)} tab={historyOpen ? "history" : "board"} primaryLabel={selection ? "Region" : "Board"} onTabChange={value => { setHistoryOpen(value === "history"); setInspectorOpen(true); }} onClose={() => { setInspectorOpen(false); setHistoryOpen(false); setLayersOpen(false); }} context={`Board: ${content.name}${selection ? " · Region: " + selection.region.name : ""}`} primary={inspector} history={versions} hosts={{ onAssistantHost, onComposerHost, assistantOpen, onToggleAssistant }} />
    </div>
    <footer className="canvas-footer canvas-editor-status"><span>{content.artboard.width} × {content.artboard.height} · {content.regions.length} regions</span><span>{busyResult ? busyResult.statusMessage : `${profileInfo.family} regenerates the whole composition`}</span><button type="button" className="text-button" onClick={() => void saveNow().catch(() => {})} disabled={!dirty || saving || conflict}><Save size={13} />Save now</button></footer>
  </div>;
  return focus ? createPortal(whole, document.body) : whole;
}
