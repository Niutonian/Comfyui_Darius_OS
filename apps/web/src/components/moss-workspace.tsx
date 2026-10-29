"use client";
/* eslint-disable @next/next/no-img-element -- immutable local preview derivatives */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, ChevronDown, Copy, Download, Hand, Layers3, Maximize, Minus, MousePointer2, Plus, Redo2, Sparkles, PanelRightOpen, Minimize2, Undo2 } from "lucide-react";
import { api, ApiError, request } from "@/lib/api-client";
import { definitiveGenerationError, canvasApi } from "@/lib/canvas-api";
import { requestBoardSetup } from "@/lib/board-setup";
import { useWorkspaceState } from "@/lib/workspace-session";
import { subscribeProjectRefresh } from "@/lib/project-sync";
import { useDariusStore } from "@/lib/store";
import { mossApi, prepareBoard, fitPlacements, fitCardToArtwork, worldPoint, boardStatus, type Placement, type MossBoard, type BoardSettings, type VisualReference, type SelectedBoardContext } from "@/lib/moss-workspace";
import { CanvasProfileControls, CanvasGenerationDetails } from "./canvas-profile-controls";
import { canvasProfiles, MOSS, FIBO_DEV, H3_ANIMATE, type CanvasProfile } from "@/lib/canvas-profile";
import { loadCanvasIntent } from "@/lib/canvas-intent";
import type { ImageProfile } from "@/lib/moss-workspace";
import type { Asset } from "@/lib/types";
import { CanvasEditor, type CanvasHosts } from "./canvas-workspace";
import { ImageRecipeControls, ImageRecipeEditor, ImageRecipeInputPreview, imageRecipeDefaults, imageRecipes, isImageRecipeBoard } from "./image-recipe-board";
import { VideoBoardControls, VideoBoardEditor, VideoCardPreview, isVideoBoard, videoDefaults } from "./video-board";
import { CanvasUtilityPanel, useCanvasNarrow, type CanvasUtilityTab } from "./canvas-utility-panel";
import { useCanvasMiddlePan } from "@/lib/use-canvas-middle-pan";

type Camera = { x: number; y: number; scale: number };
type Layout = { revision: number; saved: Placement[]; present: Placement[] };
type UndoAction = { kind: "layout"; before: Placement[]; after: Placement[] } | { kind: "board"; boardId: string; before: BoardSettings; after: BoardSettings };
type Intent = { key: string; revision: number; seed: number | string | null; profileId?: string; boardId: string; boardRevision: number; documentId: string };
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const errorText = (error: unknown) => error instanceof Error ? error.message : "The operation failed. Your board and results are retained.";
const isField = (target: EventTarget | null) => target instanceof HTMLElement && Boolean(target.closest("input,textarea,select,[contenteditable=true]"));

function BoardPreview({ board, large = false }: { board: MossBoard; large?: boolean }) {
  const asset = board.activeResult?.assetIds[0];
  const thumbnail = useQuery({ queryKey: ["moss-thumbnail", asset], enabled: Boolean(asset && !board.previewAssetId), staleTime: Infinity, retry: 1,
    queryFn: async () => (await request<{ derivatives: Asset[] }>(`/assets/${encodeURIComponent(asset!)}/derivatives?thumbnail_only=true`, { method: "POST" })).derivatives.find(a => a.metadata.derivative_type === "thumbnail")?.id });
  const image = board.previewAssetId ?? thumbnail.data;
  if (isImageRecipeBoard(board) && !board.activeResult) return <ImageRecipeInputPreview board={board} />;
  if (isVideoBoard(board)) return <VideoCardPreview board={board} />;
  return <div className={`moss-preview ${large ? "large" : ""}`}>
    {image ? <><img className="moss-image-backdrop" src={api.assetContentUrl(image)} alt="" aria-hidden="true" loading="lazy" draggable={false} /><img className="moss-image-artwork" src={api.assetContentUrl(image)} alt={`${board.name} · selected result`} loading="lazy" draggable={false} /></> : <svg role="img" aria-label={`${board.name} layout preview`} viewBox={`0 0 ${board.artboard.width} ${board.artboard.height}`}><rect width="100%" height="100%" fill="#f8f4e9" />{board.layout.map(r => <rect key={r.id} x={r.rect[0]} y={r.rect[1]} width={r.rect[2]} height={r.rect[3]} fill="none" stroke={r.kind === "text" ? "#bc8f59" : "#819c83"} strokeWidth={5} strokeDasharray={r.kind === "group" ? "16 10" : undefined} />)}</svg>}
    {!asset && !board.layout.length ? <span>Space for an idea</span> : null}
    {asset && !image ? <span>Preparing thumbnail…</span> : null}
  </div>;
}

function VisualNoteThumbnail({ assetId }: { assetId: string }) {
  const thumbnail = useQuery({ queryKey: ["moss-thumbnail", assetId], staleTime: Infinity, retry: 1,
    queryFn: async () => (await request<{ derivatives: Asset[] }>(`/assets/${encodeURIComponent(assetId)}/derivatives?thumbnail_only=true`, { method: "POST" })).derivatives.find(a => a.metadata.derivative_type === "thumbnail")?.id });
  return thumbnail.data ? <img className="moss-note-thumbnail" alt="Pinned immutable visual note — not sent to MOSS" src={api.assetContentUrl(thumbnail.data)} loading="lazy" /> : <small>{thumbnail.isLoading ? "Loading pinned version…" : "Reference preview unavailable"}</small>;
}

export function MossWorkspace({ projectId, assets, onBoardContext, expanded = false, onToggleExpanded, onExitWorkspace, ...hosts }: CanvasHosts & { projectId: string; assets: Asset[]; onBoardContext?: (context: SelectedBoardContext | null) => void; expanded?: boolean; onToggleExpanded?: () => void; onExitWorkspace?: () => void }) {
  const client = useQueryClient(), projectName = useDariusStore(s => s.projects.find(p => p.id === projectId)?.name ?? "Project");
  const scope = `moss:${projectId}`;
  const narrow = useCanvasNarrow();
  const [panelOpen, setPanelOpen] = useState<boolean | null>(null), [panelTab, setPanelTab] = useState<CanvasUtilityTab>("board");
  const query = useQuery({ queryKey: ["moss-workspace", projectId], queryFn: () => mossApi.get(projectId), refetchInterval: 2500 });
  const engine = useQuery({ queryKey: ["canvas-engine"], queryFn: () => canvasApi.engine() });
  const [layout, setLayout] = useWorkspaceState<Layout | null>(`${scope}:layout`, null);
  const [selectedId, setSelectedId] = useWorkspaceState<string | null>(`${scope}:selected`, null);
  const [openId, setOpenId] = useWorkspaceState<string | null>(`${scope}:editor`, null);
  const [camera, setCamera] = useWorkspaceState<Camera>(`${scope}:camera`, { x: 80, y: 60, scale: .8 });
  const [history, setHistory] = useWorkspaceState<{ past: UndoAction[]; future: UndoAction[] }>(`${scope}:history`, { past: [], future: [] });
  const [intents, setIntents] = useWorkspaceState<Record<string, Intent>>(`${scope}:intents`, {});
  const [editorPreparing] = useWorkspaceState<Record<string, boolean>>(`canvas:${projectId}:preparing`, {}); const [preparing, setPreparing] = useState<Set<string>>(new Set()), [boardErrors, setBoardErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState(""), [saving, setSaving] = useState(false), [conflict, setConflict] = useState(false), [creating, setCreating] = useState(false);
  const [search, setSearch] = useState(""), [hand, setHand] = useState(false), [space, setSpace] = useState(false), [archives, setArchives] = useState(false);
  const [size, setSize] = useState({ width: 1000, height: 700 }), [dragged, setDragged] = useState<Placement | null>(null);
  const [videoTarget, setVideoTarget] = useState("new"), [videoRole, setVideoRole] = useState<"animate-image" | "camera-direction" | "reference-video">("animate-image");
  const [referenceTarget, setReferenceTarget] = useState(""), [referenceGeneration, setReferenceGeneration] = useState("");
  const stage = useRef<HTMLDivElement>(null), importer = useRef<HTMLInputElement>(null), currentLayout = useRef(layout), savingPromise = useRef<Promise<void> | null>(null), initialized = useRef(false);
  const { panning: middlePanning, attach: attachMiddlePan } = useCanvasMiddlePan(stage, camera, setCamera);
  const preparingIds = useRef(new Set<string>());
  // React delegates wheel events passively; bind locally to keep the page still.
  useEffect(() => {
    const node = stage.current;
    if (!node) return;
    const wheel = (event: WheelEvent) => {
      if ((event.target as Element).closest("input,textarea,select,[contenteditable=true]")) return;
      event.preventDefault();
      const rect = node.getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top;
      setCamera(current => {
        if (event.shiftKey) return { ...current, x: current.x - event.deltaX, y: current.y - event.deltaY };
        if (!event.deltaY) return current;
        const scale = Math.max(.15, Math.min(2, current.scale * (event.deltaY > 0 ? .92 : 1.08)));
        return { scale, x: x - (x - current.x) * scale / current.scale, y: y - (y - current.y) * scale / current.scale };
      });
    };
    node.addEventListener("wheel", wheel, { passive: false });
    return () => node.removeEventListener("wheel", wheel);
  });
  const gesture = useRef<({ pointerId: number; x: number; y: number; moved: boolean } & ({ type: "pan"; camera: Camera } | { type: "board"; scale: number; placement: Placement; next: Placement })) | null>(null);
  const suppressBoardClick = useRef(false);
  const pointerBoard = useRef<string | null>(null);
  useLayoutEffect(() => { currentLayout.current = layout; }, [layout]);
  const boards = query.data?.boards ?? [], selected = boards.find(b => b.id === selectedId), opened = boards.find(b => b.id === openId);
  const selectedPlacement = layout?.present.find(p => p.boardId === selectedId);
  const visibleBoards = boards.filter(b => b.archived === archives && b.name.toLowerCase().includes(search.toLowerCase()));
  const dirty = Boolean(layout && !equal(layout.present, layout.saved));
  const activeJobs = boards.flatMap(b => b.jobs);
  const refresh = useCallback(() => { void client.invalidateQueries({ queryKey: ["moss-workspace", projectId] }); void client.invalidateQueries({ queryKey: ["canvas", projectId] }); }, [client, projectId]);
  useEffect(() => subscribeProjectRefresh(projectId, e => { if (e.full || e.types.some(t => /^(canvas\.|job\.|generation\.|asset\.)/.test(t))) refresh(); }), [projectId, refresh]);
  useEffect(() => {
    const remote = query.data;
    if (!remote) return;
    const local = currentLayout.current;
    const editingPosition = gesture.current?.type === "board" || (document.activeElement instanceof HTMLElement && Boolean(document.activeElement.closest(".moss-card-placement")));
    if (local && editingPosition) {
      if (remote.revision > local.revision) { setConflict(true); setError("Workspace positions changed during this edit. Your position draft is retained; export it or reload saved positions to resolve."); }
      return;
    }
    if (!local || (!savingPromise.current && equal(local.present, local.saved))) setLayout({ revision: remote.revision, saved: remote.placements, present: remote.placements });
    else if (remote.revision > local.revision && !savingPromise.current) { setConflict(true); setError("Workspace positions changed on another device. Your position draft is retained; board generation still works."); }
    if (!initialized.current) {
      initialized.current = true; setIntents(current => { const next = { ...current }; for (const board of remote.boards) { const pending = loadCanvasIntent(projectId, board.documentId); if (pending?.boardId && pending.boardRevision) next[board.id] = { ...pending, boardId: pending.boardId, boardRevision: pending.boardRevision }; } return next; });
      try { const value = JSON.parse(localStorage.getItem(`${scope}:view`) ?? "null"); if (value?.camera?.scale >= .15 && value.camera.scale <= 2) { setCamera(value.camera); setSelectedId(value.selectedId); } } catch {}
      const params = new URLSearchParams(location.search), linked = remote.boards.find(b => b.id === params.get("board") || b.documentId === params.get("canvas"));
      if (linked) { setOpenId(linked.id); setSelectedId(linked.id); }
    }
  }, [query.data, scope, projectId, setIntents, setLayout, setCamera, setSelectedId, setOpenId]);
  useEffect(() => { if (initialized.current) localStorage.setItem(`${scope}:view`, JSON.stringify({ camera, selectedId })); }, [camera, selectedId, scope]);
  useEffect(() => {
    const node = stage.current; if (!node) return;
    const resize = () => setSize({ width: node.clientWidth, height: node.clientHeight }); resize();
    const observer = new ResizeObserver(resize); observer.observe(node); return () => observer.disconnect();
  }, [openId]);
  useEffect(() => {
    if (!selected) { onBoardContext?.(null); return; }
    const board = selected;
    onBoardContext?.({ boardId: board.id, documentId: board.documentId, documentRevision: board.documentRevision, boardRevision: board.revision, name: board.name, prepare: () => prepareBoard(projectId, board) });
    return () => onBoardContext?.(null);
  }, [selected, projectId, onBoardContext]);
  async function saveLayout() {
    if (savingPromise.current) return savingPromise.current;
    const local = currentLayout.current;
    if (!local || equal(local.present, local.saved) || conflict) return;
    setSaving(true);
    const work = mossApi.layout(projectId, local.revision, local.present).then(remote => {
      setLayout(previous => previous ? { ...previous, revision: remote.revision, saved: local.present } : previous);
      client.setQueryData(["moss-workspace", projectId], remote);
    }).catch(e => { setError(errorText(e)); if (e instanceof ApiError && e.status === 409) setConflict(true); throw e; })
      .finally(() => { savingPromise.current = null; setSaving(false); });
    savingPromise.current = work; return work;
  }
  useEffect(() => { if (!dirty || saving || conflict) return; const timer = setTimeout(() => { void saveLayout().catch(() => {}); }, 650); return () => clearTimeout(timer); });
  function record(action: UndoAction) { setHistory(h => ({ past: [...h.past.slice(-49), action], future: [] })); }
  function move(placement: Placement) {
    if (!layout) return;
    const next = layout.present.map(p => p.boardId === placement.boardId ? placement : p);
    if (!equal(next, layout.present)) { record({ kind: "layout", before: layout.present, after: next }); setLayout({ ...layout, present: next }); }
  }
  function fitArtwork(board: MossBoard) {
    const placement = currentLayout.current?.present.find(p => p.boardId === board.id);
    if (!placement) return;
    const image = assets.find(a => a.id === board.activeResult?.assetIds[0]);
    move(fitCardToArtwork(placement, image?.width && image.height ? { width: image.width, height: image.height } : board.artboard));
  }
  async function undoAction(forward: boolean) {
    const action = forward ? history.future[0] : history.past.at(-1); if (!action) return;
    try {
      if (action.kind === "layout") setLayout(l => l ? { ...l, present: l.present.map(p => (forward ? action.after : action.before).find(old => old.boardId === p.boardId) ?? p) } : l);
      else { const board = boards.find(b => b.id === action.boardId); if (!board) throw new Error("Board no longer exists"); const saved = await mossApi.save(projectId, board, forward ? action.after : action.before); client.setQueryData<import("@/lib/moss-workspace").ProjectWorkspace>(["moss-workspace", projectId], old => old ? { ...old, boards: old.boards.map(b => b.id === saved.id ? saved : b) } : old); refresh(); }
      setHistory(h => forward ? { past: [...h.past, action], future: h.future.slice(1) } : { past: h.past.slice(0, -1), future: [action, ...h.future] });
    } catch (e) { setError(errorText(e)); }
  }
  async function add(duplicate?: MossBoard, content?: import("@/lib/canvas-document").CanvasContent, profile: CanvasProfile = MOSS) {
    setCreating(true); setError("");
    try {
      await saveLayout();
      if (duplicate) await prepareBoard(projectId, duplicate);
      const centre = worldPoint({ x: size.width / 2 - 180, y: size.height / 2 - 225 }, camera);
      const result = await mossApi.add(projectId, { x: centre.x, y: centre.y, name: duplicate ? `${duplicate.name.slice(0, 180)} copy` : profile === H3_ANIMATE ? "Untitled video" : imageRecipes.includes(profile as ImageProfile) ? "Untitled image" : "Untitled board", duplicateBoardId: duplicate?.id, content, settings: { adapterVersion: profile, seed: null, references: [], ...(profile === H3_ANIMATE ? { video: videoDefaults() } : {}), ...(imageRecipes.includes(profile as ImageProfile) ? { image: imageRecipeDefaults(profile as ImageProfile) } : {}) } });
      client.setQueryData(["moss-workspace", projectId], result.workspace);
      setLayout({ revision: result.workspace.revision, saved: result.workspace.placements, present: result.workspace.placements });
      setSelectedId(result.boardId); setArchives(false); setSearch("");
    } catch (e) { setError(errorText(e)); } finally { setCreating(false); }
  }
  async function bindImageToVideo(source: MossBoard) {
    try {
      const asset = assets.find(a => a.id === source.activeResult?.assetIds[0]);
      if (!asset || asset.kind !== "image") throw new Error("Select a completed image result first.");
      const target = boards.find(b => b.id === videoTarget), config = structuredClone(target?.settings.video ?? videoDefaults());
      config.activeMode = videoRole;
      const draft = config.modeDrafts[videoRole];
      if (draft.inputs.length >= (videoRole === "reference-video" ? 9 : 1)) throw new Error("Clear the current input in the target video mode before replacing it.");
      draft.inputs.push({ id: crypto.randomUUID(), assetId: asset.id, assetVersionId: asset.content_hash, mediaKind: "image", role: videoRole === "animate-image" ? "starting-frame" : videoRole === "camera-direction" ? "camera-source" : "subject", token: draft.inputs.length + 1 });
      const adapterVersion = `minimax-h3-${videoRole}-v1` as CanvasProfile;
      if (target) { await settings(target, { ...target.settings, adapterVersion, video: config }); setSelectedId(target.id); }
      else {
        await saveLayout();
        const centre = worldPoint({ x: size.width / 2 - 180, y: size.height / 2 - 225 }, camera);
        const added = await mossApi.add(projectId, { ...centre, name: `${source.name.slice(0,170)} video`, settings: { adapterVersion, video: config, seed: null, references: [] } });
        client.setQueryData(["moss-workspace", projectId], added.workspace); setLayout({ revision: added.workspace.revision, saved: added.workspace.placements, present: added.workspace.placements }); setSelectedId(added.boardId);
      }
      refresh();
    } catch (error) { setError(errorText(error)); }
  }
  function jump(board: MossBoard) {
    setSelectedId(board.id); setArchives(board.archived);
    const placement = layout?.present.find(p => p.boardId === board.id);
    if (placement) setCamera(fitPlacements([placement], size));
  }
  function open(board: MossBoard) { setSelectedId(board.id); if (board.archived) return; setOpenId(board.id); const url = new URL(location.href); url.searchParams.delete("canvas"); url.searchParams.set("board", board.id); historyReplace(url); }
  function closeEditor() { if (opened) void prepareBoard(projectId, opened).catch(e => setBoardErrors(errors => ({ ...errors, [opened.id]: errorText(e) }))); setOpenId(null); const url = new URL(location.href); url.searchParams.delete("board"); url.searchParams.delete("canvas"); historyReplace(url); refresh(); }
  const preparingBoard = (board: MossBoard) => preparing.has(board.id) || Boolean(editorPreparing[board.documentId]);
  const statusFor = (board: MossBoard) => boardStatus(board, preparingBoard(board), boardErrors[board.id]);
  const generateLabel = (board: MossBoard) => preparingBoard(board) ? "Preparing…" : board.jobs.some(job => job.status === "running" || job.status === "cancelling") ? "Rendering…" : board.jobs.length ? "Queued" : intents[board.id] ? "Retry request" : isVideoBoard(board) ? "Generate video" : isImageRecipeBoard(board) ? canvasProfiles[board.settings.adapterVersion].action : "Generate";
  async function generate(board: MossBoard) {
    if (preparingIds.current.has(board.id)) return;
    setSelectedId(board.id);
    setError(current => current.startsWith(`${board.name}: `) ? "" : current);
    preparingIds.current.add(board.id); setPreparing(new Set(preparingIds.current)); setBoardErrors(e => ({ ...e, [board.id]: "" }));
    try {
      let intent = intents[board.id];
      if (!intent) { const snapshot = await prepareBoard(projectId, board); intent = { ...snapshot, key: crypto.randomUUID(), revision: snapshot.documentRevision, seed: snapshot.seed === undefined ? board.settings.seed : snapshot.seed, profileId: snapshot.profileId ?? board.settings.adapterVersion }; setIntents(i => ({ ...i, [board.id]: intent })); }
      const result = await canvasApi.generate(projectId, intent.documentId, intent.revision, intent.key, intent.seed, intent, () => setBoardErrors(e => ({ ...e, [board.id]: "Checking whether your job was queued..." })));
      client.setQueryData<import("@/lib/moss-workspace").ProjectWorkspace>(["moss-workspace", projectId], old => old ? { ...old, boards: old.boards.map(current => current.id !== board.id ? current : { ...current, latest: result, jobs: ["queued", "running", "cancelling"].includes(result.status) ? [result, ...current.jobs.filter(job => job.id !== result.id)] : current.jobs.filter(job => job.id !== result.id) }) } : old);
      setIntents(i => { const next = { ...i }; delete next[board.id]; return next; });
      setBoardErrors(e => ({ ...e, [board.id]: result.launchError ?? "" }));
      refresh(); void client.invalidateQueries({ queryKey: ["jobs"] });
    } catch (e) {
      setBoardErrors(errors => ({ ...errors, [board.id]: errorText(e) }));
      setError(`${board.name}: ${errorText(e)}`);
      if (definitiveGenerationError(e)) setIntents(i => { const next = { ...i }; delete next[board.id]; return next; });
    } finally { preparingIds.current.delete(board.id); setPreparing(new Set(preparingIds.current)); }
  }
  async function settings(board: MossBoard, next: BoardSettings, remember = true) {
    try { const saved = await mossApi.save(projectId, board, next); client.setQueryData<import("@/lib/moss-workspace").ProjectWorkspace>(["moss-workspace", projectId], old => old ? { ...old, boards: old.boards.map(b => b.id === saved.id ? saved : b) } : old); if (remember) record({ kind: "board", boardId: board.id, before: board.settings, after: next }); refresh(); return true; }
    catch (e) { setBoardErrors(errors => ({ ...errors, [board.id]: errorText(e) })); return false; }
  }
  const sourceVersions = useQuery({ queryKey: ["canvas", projectId, selected?.documentId], queryFn: () => canvasApi.get(projectId, selected!.documentId), enabled: Boolean(selected), refetchInterval: 5000 });
  const completed = sourceVersions.data?.generations.filter(g => g.status === "completed" && g.assetIds.length) ?? [];
  const chosenVersion = completed.find(g => g.id === referenceGeneration);
  const chosenAsset = assets.find(a => a.id === chosenVersion?.assetIds[0] && a.project_id === projectId);
  async function pin() {
    const target = boards.find(b => b.id === referenceTarget);
    if (!selected || !target || !chosenVersion || !chosenAsset) return;
    const previous = target.settings.references.find(r => r.sourceBoardId === selected.id);
    if (previous && !confirm(`Update ${target.name}'s pinned note to this explicitly chosen version? Already submitted generations keep the old version.`)) return;
    const ref: VisualReference = { id: previous?.id ?? crypto.randomUUID(), sourceBoardId: selected.id, sourceGenerationId: chosenVersion.id, assetId: chosenAsset.id, assetVersionId: chosenAsset.content_hash, role: "visual-note" };
    if (await settings(target, { ...target.settings, references: previous ? target.settings.references.map(r => r.id === previous.id ? ref : r) : [...target.settings.references, ref] })) { setReferenceGeneration(""); setReferenceTarget(""); } else setError("The target board could not save this visual note. Your version selection is retained; refresh and retry.");
  }
  const boardPanel = selected && isImageRecipeBoard(selected) ? <ImageRecipeControls board={selected} assets={assets} onChange={async next => { if (!await settings(selected, next)) throw new Error("Image settings could not save; refresh before retrying."); }} onError={setError} /> : selected && isVideoBoard(selected) ? <VideoBoardControls board={selected} assets={assets} onChange={async next => { if (!await settings(selected, next)) throw new Error("Video settings could not save; refresh before retrying."); }} onError={setError} /> : selected ? <section className="moss-inspector" aria-label="Selected board"><header><div><small>Selected board</small><strong>{selected.name}</strong></div></header>
      <label>Board name<input key={`${selected.id}:${selected.name}`} defaultValue={selected.name} maxLength={200} onBlur={async e => { const name = e.target.value.trim(); if (!name || name === selected.name) return; try { await prepareBoard(projectId, selected); const doc = await canvasApi.get(projectId, selected.documentId); await canvasApi.save(projectId, selected.documentId, doc.revision, { ...doc.content, name }); refresh(); } catch (error) { setBoardErrors(errors => ({ ...errors, [selected.id]: errorText(error) })); } }} /></label>
      <p className="canvas-help">{canvasProfiles[selected.settings.adapterVersion].family} · {canvasProfiles[selected.settings.adapterVersion].name}</p><CanvasProfileControls board={selected} onChange={next => settings(selected, next)} onError={setError} /><label>Saved composition prompt<textarea readOnly value={sourceVersions.data?.content.globalPrompt ?? selected.prompt} rows={4} /><small>Edit the prompt in the focused editor.</small></label><div className="canvas-composition-summary"><span>{selected.artboard.width} × {selected.artboard.height}</span><span>{selected.regionCount} regions</span></div>{selected.activeResult ? <p className="canvas-help">Showing result r{selected.activeResult.revision}{selected.documentRevision !== selected.activeResult.revision ? ` · Layout r${selected.documentRevision} has newer edits` : ""}{selected.newResult ? " · New result in History" : ""}</p> : null}<button className="secondary-button" disabled={selected.archived} onClick={() => open(selected)}>Open focused editor <ArrowRight size={14} /></button><button className="primary-button moss-panel-generate" disabled={selected.archived || preparingBoard(selected) || Boolean(selected.jobs.length)} onClick={() => void generate(selected)}><Sparkles size={15} />{generateLabel(selected)}</button><p className="canvas-help" role="status">{statusFor(selected)}{selected.jobs[0] ? ` · ${selected.jobs[0].statusMessage}` : preparingBoard(selected) ? " · Saving and validating this composition" : ""}</p><button className="secondary-button" disabled={creating || selected.archived} onClick={() => void add(selected)}><Copy size={14} />Duplicate board</button><details className="canvas-board-settings"><summary>Generation settings & arrangement</summary>
      {selectedPlacement ? <details className="moss-card-placement"><summary>Workspace position &amp; card size</summary><p className="canvas-help">Presentation only. The output remains {selected.artboard.width} × {selected.artboard.height}.</p>{(["x", "y", "displayWidth", "displayHeight"] as const).map(key => <label key={`${selected.id}:${key}:${selectedPlacement[key]}`}>{key}<input type="number" defaultValue={Math.round(selectedPlacement[key])} onBlur={e => { const value = Number(e.target.value); if (!Number.isFinite(value)) return; const min = key === "displayWidth" ? 280 : key === "displayHeight" ? 350 : -100000, max = key === "displayWidth" ? 800 : key === "displayHeight" ? 900 : 100000; move({ ...selectedPlacement, [key]: Math.max(min, Math.min(max, value)) }); }} /></label>)}</details> : null}
      <button className="text-button" onClick={() => fitArtwork(selected)}><Maximize size={14} />Fit card to artwork proportions</button>
      <button className="text-button" onClick={() => jump(selected)}>Fit selected board</button>
      <button className="text-button" onClick={async () => { if (!confirm(selected.archived ? "Restore this board?" : "Archive this board? Its document, assets and pending jobs are retained.")) return; try { await mossApi.save(projectId, selected, selected.settings, !selected.archived); refresh(); setSelectedId(null); } catch (e) { setError(errorText(e)); } }}>{selected.archived ? "Restore to workspace" : "Archive from workspace"}</button>
</details>
      {selected.jobs.map(j => <div className="moss-job" key={j.id}><strong>{j.status === "queued" ? "Queued" : j.statusMessage} · r{j.revision}</strong>{j.status === "queued" ? <button onClick={() => void mossApi.cancel(projectId, selected.id, j.jobId).then(refresh).catch(e => setError(errorText(e)))}>Cancel queued job</button> : <small>Running work is not globally interrupted.</small>}</div>)}
      {selected.jobs.some(j => j.status === "queued") ? <button className="text-button" onClick={async () => { const j = selected.jobs.find(j => j.status === "queued"); if (j) { try { await canvasApi.start(projectId, selected.documentId, j.id); refresh(); } catch (e) { setError(errorText(e)); } } }}>Wake shared worker</button> : null}
      {boardErrors[selected.id] || selected.latest?.error ? <p className="form-error" role="alert">{boardErrors[selected.id] || selected.latest?.error}</p> : null}
      {selected.activeResult?.assetIds[0] ? <details className="h3-transfer"><summary>Use in video board</summary><label>Video board<select value={videoTarget} onChange={e => setVideoTarget(e.target.value)}><option value="new">Create a new Video board</option>{boards.filter(b => isVideoBoard(b) && !b.archived).map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label><label>Input role<select value={videoRole} onChange={e => setVideoRole(e.target.value as typeof videoRole)}><option value="animate-image">Starting frame</option><option value="camera-direction">Camera source</option><option value="reference-video">Reference image</option></select></label><button className="secondary-button" onClick={() => void bindImageToVideo(selected)}>Pin this exact image version</button><small>Only binds the selected result. Generate when ready.</small></details> : null}
      <details className="moss-references"><summary>Pinned visual notes</summary><p className="canvas-help">Visual reference — not sent to MOSS. Connections never queue work.</p>{selected.settings.references.map(ref => { const source = boards.find(b => b.id === ref.sourceBoardId), newer = source?.latest?.status === "completed" && source.latest.id !== ref.sourceGenerationId; return <div className="moss-reference" key={ref.id}><VisualNoteThumbnail assetId={ref.assetId} /><strong>{source?.name ?? "Archived source"}</strong><small>Version {ref.sourceGenerationId.slice(0,8)} · {ref.assetVersionId.slice(0,12)}</small>{newer ? <small>New version available · select it explicitly on the source board to update this note.</small> : null}<button className="text-button" onClick={() => { if (source) jump(source); }}>Jump to source</button><button className="text-button" onClick={() => void settings(selected, { ...selected.settings, references: selected.settings.references.filter(r => r.id !== ref.id) })}>Remove connection</button></div>; })}</details>
      <details className="moss-pin"><summary>Pin a completed result</summary><label>Exact result version<select value={referenceGeneration} onChange={e => setReferenceGeneration(e.target.value)}><option value="">Choose a version…</option>{completed.map(g => <option value={g.id} key={g.id}>r{g.revision} · seed {g.seed} · {g.createdAt.slice(0,16)}</option>)}</select></label>{chosenAsset ? <><img alt="Chosen immutable reference version" src={api.assetContentUrl(chosenAsset.id)} /><small>Asset {chosenAsset.id.slice(0,8)} · hash {chosenAsset.content_hash.slice(0,12)}</small><button className="text-button" onClick={async () => { if (chosenVersion) { await canvasApi.select(projectId, selected.documentId, chosenVersion.id); refresh(); } }}>Display this result on source board</button></> : null}
        <label>Target board<select value={referenceTarget} onChange={e => setReferenceTarget(e.target.value)}><option value="">Choose another board…</option>{boards.filter(b => b.id !== selected.id && !b.archived).map(b => <option value={b.id} key={b.id}>{b.name}</option>)}</select></label><button className="secondary-button" disabled={!chosenAsset || !referenceTarget} onClick={() => void pin()}>Confirm visual reference</button></details>
    </section> : <div className="canvas-panel-empty"><Layers3 size={28} /><h3>Choose a board</h3><p>Select a board to see its composition, settings and saved versions.</p></div>;
  const historyPanel = selected ? <section className="canvas-board-history"><h3>{selected.name} · versions</h3>
    <div className="canvas-draft-entry"><Layers3 size={18} /><div><strong>Draft r{sourceVersions.data?.revision ?? selected.documentRevision}</strong><small>Saved layout · {selected.activeResult && selected.activeResult.revision !== selected.documentRevision ? "newer edits than the displayed result" : "current composition"}</small></div></div>
    {sourceVersions.isLoading ? <p>Loading versions…</p> : null}{sourceVersions.isError ? <p role="alert">Versions could not load. <button onClick={() => void sourceVersions.refetch()}>Retry</button></p> : null}
    {sourceVersions.data?.generations.map(result => <div className="canvas-version" key={result.id}><button type="button" disabled={result.status !== "completed"} aria-pressed={selected.activeResult?.id === result.id} onClick={async () => { try { await canvasApi.select(projectId, selected.documentId, result.id); refresh(); void sourceVersions.refetch(); } catch (error) { setError(errorText(error)); } }}>
      {result.assetIds[0] ? <VisualNoteThumbnail assetId={result.assetIds[0]} /> : <Layers3 size={20} />}<span>Result from r{result.revision}<small>{result.status} · seed {result.seed}</small><small>{result.createdAt.slice(0,16).replace("T", " ")}</small></span></button><CanvasGenerationDetails result={result} board={selected} projectId={projectId} generations={sourceVersions.data?.generations ?? []} onError={setError} />{result.error ? <p>{result.error}</p> : null}</div>)}
    {!sourceVersions.isLoading && !sourceVersions.data?.generations.length ? <p>No generated versions yet.</p> : null}
  </section> : <div className="canvas-panel-empty"><p>Select a board to browse its saved results.</p></div>;
  if (opened && !opened.archived && isImageRecipeBoard(opened)) return <ImageRecipeEditor key={opened.id} board={opened} projectId={projectId} assets={assets} onExit={closeEditor} onGenerate={() => generate(opened)} onVideo={() => void bindImageToVideo(opened)} {...hosts} />;
  if (opened && !opened.archived && isVideoBoard(opened)) return <VideoBoardEditor key={opened.id} board={opened} projectId={projectId} assets={assets} onExit={closeEditor} onGenerate={() => generate(opened)} {...hosts} />;
  if (opened && !opened.archived) return <CanvasEditor key={`${projectId}:${opened.documentId}`} projectId={projectId} documentId={opened.documentId} assets={assets} {...hosts} chooser={null} presets={engine.data?.presets ?? []} onExit={closeEditor} board={opened} />;
  return <section className="canvas-workspace moss-workspace canvas-refined" aria-label="MOSS board workspace" tabIndex={0} onKeyDown={e => {
    if (isField(e.target)) return;
    if (e.code === "Space") { e.preventDefault(); setSpace(true); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); void undoAction(e.shiftKey); }
    if (e.key === "Escape" && hosts.assistantOpen) { hosts.onToggleAssistant?.(); }
  }} onKeyUp={e => { if (e.code === "Space") setSpace(false); }} onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) setSpace(false); }}>
    <header className="moss-toolbar"><div className="moss-project-heading">{onExitWorkspace ? <button className="icon-button" aria-label="Back to Library" onClick={onExitWorkspace}><ArrowLeft size={17} /></button> : null}<span>{projectName} <small>/ Canvas</small></span></div>
      <div className="moss-navigation"><label><Layers3 size={15} /><input aria-label="Search boards" placeholder="Find a board…" value={search} onChange={e => setSearch(e.target.value)} /></label><select aria-label="Jump to board" value={selectedId ?? ""} onChange={e => { const b = boards.find(b => b.id === e.target.value); if (b) jump(b); }}><option value="">Jump to board…</option>{boards.map(b => <option key={b.id} value={b.id}>{b.name}{b.archived ? " · archived" : ""}</option>)}</select><button className="text-button" onClick={() => setArchives(v => !v)}>{archives ? "Show workspace" : "Archived"}</button></div>
      <div className="moss-toolbar-actions"><button className="secondary-button canvas-add-board" aria-label="Add MOSS board" disabled={creating} onClick={() => void add()}><Plus size={16} /><span className="canvas-add-full">MOSS board</span><span className="canvas-add-short" aria-hidden="true">MOSS</span></button><button className="secondary-button canvas-add-board" aria-label="Add FIBO board" disabled={creating} onClick={() => void add(undefined, undefined, FIBO_DEV)}><Plus size={16} /><span className="canvas-add-full">FIBO board</span><span className="canvas-add-short" aria-hidden="true">FIBO</span></button><details className="image-recipe-add"><summary className="secondary-button canvas-add-board" aria-label="Add image board" aria-disabled={creating} onClick={e => { if (creating) e.preventDefault(); }}><Plus size={16} /><span className="canvas-add-full">Image board</span><span className="canvas-add-short" aria-hidden="true">Image</span><ChevronDown size={12} className="canvas-add-chevron" /></summary><div>{imageRecipes.map(profile => <button type="button" key={profile} disabled={creating} onClick={e => { e.currentTarget.closest("details")!.open = false; void add(undefined, undefined, profile); }}>{canvasProfiles[profile].name}</button>)}</div></details><button className="secondary-button canvas-add-board canvas-add-video" aria-label="Add video board" disabled={creating} onClick={() => void add(undefined, undefined, H3_ANIMATE)}><Plus size={16} /><span className="canvas-add-full">Video board</span><span className="canvas-add-short" aria-hidden="true">Video</span></button><button className="icon-button" aria-label="Import Canvas as board" onClick={() => importer.current?.click()}><Download size={17} /></button>
        <input type="file" ref={importer} hidden accept="application/json,.json" onChange={async e => { const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; if (file.size > 256000) { setError("Canvas JSON is limited to 256 KB"); return; } try { await add(undefined, JSON.parse(await file.text())); } catch (error) { setError(errorText(error)); } }} />
        <button className="text-button" disabled={!selected} onClick={() => { if (selected) void requestBoardSetup(selected.settings.adapterVersion).catch(error => setError(errorText(error))); }}>Prepare board</button>
        <button className="icon-button" aria-label="Select boards" aria-pressed={!hand} onClick={() => setHand(false)}><MousePointer2 size={17} /></button><button className="icon-button" aria-label="Pan workspace" aria-pressed={hand} onClick={() => setHand(true)}><Hand size={17} /></button>
        <button className="icon-button" aria-label="Undo workspace action" disabled={!history.past.length} onClick={() => void undoAction(false)}><Undo2 size={17} /></button><button className="icon-button" aria-label="Redo workspace action" disabled={!history.future.length} onClick={() => void undoAction(true)}><Redo2 size={17} /></button>
        <button className="icon-button" aria-label="Zoom out workspace" onClick={() => setCamera(c => ({ ...c, scale: Math.max(.15, c.scale / 1.2) }))}><Minus size={16} /></button><span>{Math.round(camera.scale * 100)}%</span><button className="icon-button" aria-label="Zoom in workspace" onClick={() => setCamera(c => ({ ...c, scale: Math.min(2, c.scale * 1.2) }))}><Plus size={16} /></button>
        <button className="icon-button" aria-label="Open Canvas utilities" aria-expanded={(panelOpen ?? !narrow) || Boolean(hosts.assistantOpen)} onClick={() => setPanelOpen(value => !(value ?? !narrow))}><PanelRightOpen size={17} /></button>{onToggleExpanded ? <button className="icon-button" aria-label={expanded ? "Restore Canvas window" : "Expand Canvas workspace"} onClick={onToggleExpanded}>{expanded ? <Minimize2 size={17} /> : <Maximize size={17} />}</button> : null}<button className="icon-button" aria-label="Fit all boards" onClick={() => setCamera(fitPlacements(layout?.present.filter(p => visibleBoards.some(b => b.id === p.boardId)) ?? [], size))}><Maximize size={17} /></button></div>
    </header>
    {(error || query.isError) ? <div className="canvas-notice is-error" role="alert">{error || (query.data ? "Status updates are interrupted. Last known results are shown; retry to reconnect." : "Workspace could not load")}{conflict ? <><button onClick={() => { const blob = new Blob([JSON.stringify(layout?.present, null, 2)], { type: "application/json" }), a = document.createElement("a"), url = URL.createObjectURL(blob); a.href = url; a.download = "workspace-position-draft.json"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }}>Export positions</button><button onClick={async () => { if (!confirm("Reload saved positions? Your position draft will be discarded; board documents are unchanged.")) return; try { const response = await query.refetch(); if (!response.data || response.isError) throw new Error("Saved positions could not load; your draft is retained."); setLayout({ revision: response.data.revision, saved: response.data.placements, present: response.data.placements }); setHistory({ past: [], future: [] }); setConflict(false); setError(""); } catch (error) { setError(errorText(error)); } }}>Reload positions</button></> : <button onClick={() => { setError(""); refresh(); }}>Retry</button>}</div> : null}

    <div className="moss-body"><div className={`moss-stage ${hand || space ? "is-panning" : ""} ${middlePanning ? "is-middle-panning" : ""}`} ref={attachMiddlePan} tabIndex={-1} data-scale={camera.scale} data-pan-x={camera.x} data-pan-y={camera.y}

      onPointerDown={e => {
        if (e.button !== 0 && e.button !== 1 || gesture.current) return;
        suppressBoardClick.current = false;
        const target = e.target as Element;
        if (target.closest("button,input,select,textarea,a,video,[contenteditable=true]")) return;
        const boardId = target.closest<HTMLElement>(".moss-board")?.dataset.boardId;
        const placement = currentLayout.current?.present.find(p => p.boardId === boardId);
        e.preventDefault(); e.currentTarget.focus({ preventScroll: true }); e.currentTarget.setPointerCapture(e.pointerId);
        const start = { pointerId: e.pointerId, x: e.clientX, y: e.clientY, moved: false };
        if (placement && !hand && !space && e.button === 0) {
          pointerBoard.current = placement.boardId;
          setSelectedId(placement.boardId);
          gesture.current = { ...start, type: "board", scale: camera.scale, placement, next: placement };
        } else { pointerBoard.current = null; gesture.current = { ...start, type: "pan", camera }; }
      }}
      onPointerMove={e => {
        const g = gesture.current; if (!g || g.pointerId !== e.pointerId) return;
        const dx = e.clientX - g.x, dy = e.clientY - g.y;
        if (!g.moved && Math.hypot(dx, dy) < 4) return;
        g.moved = true; suppressBoardClick.current = true;
        if (g.type === "pan") setCamera({ ...g.camera, x: g.camera.x + dx, y: g.camera.y + dy });
        else { g.next = { ...g.placement, x: Math.max(-100000, Math.min(100000, g.placement.x + dx / g.scale)), y: Math.max(-100000, Math.min(100000, g.placement.y + dy / g.scale)) }; setDragged(g.next); }
      }}
      onPointerUp={e => { const g = gesture.current; if (!g || g.pointerId !== e.pointerId) return; if (g.type === "board" && g.moved) move(g.next); else if (g.type === "board") setPanelOpen(true); gesture.current = null; setDragged(null); }}
      onPointerCancel={() => { gesture.current = null; setDragged(null); }} onLostPointerCapture={() => { gesture.current = null; setDragged(null); }}
      onClickCapture={e => { if (suppressBoardClick.current) { e.preventDefault(); e.stopPropagation(); } }} onDoubleClick={e => { if (suppressBoardClick.current || (e.target as Element).closest("button,video,a")) return; const board = boards.find(b => b.id === pointerBoard.current); if (board) open(board); }}>
      <div className="moss-world" style={{ transform: `translate(${camera.x}px,${camera.y}px) scale(${camera.scale})` }}>
        <svg className="moss-edges" aria-hidden="true">{boards.filter(b => !b.archived).flatMap(target => target.settings.references.map(ref => { const a = layout?.present.find(p => p.boardId === ref.sourceBoardId), b = layout?.present.find(p => p.boardId === target.id); if (!a || !b) return null; return <path key={`${target.id}:${ref.id}`} d={`M ${a.x + a.displayWidth} ${a.y + a.displayHeight/2} C ${a.x + a.displayWidth+100} ${a.y+a.displayHeight/2}, ${b.x-100} ${b.y+b.displayHeight/2}, ${b.x} ${b.y+b.displayHeight/2}`} />; }))}</svg>
        {visibleBoards.map(board => {
          const placement = dragged?.boardId === board.id ? dragged : layout?.present.find(p => p.boardId === board.id); if (!placement) return null;
          const visible = placement.x*camera.scale+camera.x > -placement.displayWidth*camera.scale-200 && placement.x*camera.scale+camera.x < size.width+200 && placement.y*camera.scale+camera.y > -placement.displayHeight*camera.scale-200 && placement.y*camera.scale+camera.y < size.height+200;
          return <article key={board.id} className={`moss-board ${camera.scale < .65 ? "is-compact" : ""} ${placement.displayWidth * camera.scale < 160 ? "is-tiny" : ""} ${preparingBoard(board) || board.jobs.length ? "is-busy" : ""} ${boardErrors[board.id] || board.latest?.error ? "has-error" : ""} ${board.activeResult ? "has-result" : ""} ${dragged?.boardId === board.id ? "is-dragging" : ""} ${selectedId === board.id ? "selected" : ""}`} data-board-id={board.id} style={{ left: placement.x, top: placement.y, width: placement.displayWidth, height: placement.displayHeight, zIndex: dragged?.boardId === board.id ? 3 : selectedId === board.id ? 2 : 1, "--board-label-scale": 1 / camera.scale } as import("react").CSSProperties} title="Drag the image or title to move this board. Double-click to edit." onClick={() => setSelectedId(board.id)}>
            <header><span className="moss-board-mark"><Layers3 size={17} /></span><div><strong>{board.name}</strong><small>{canvasProfiles[board.settings.adapterVersion].family} · {canvasProfiles[board.settings.adapterVersion].name}</small></div><span className={`moss-status state-${statusFor(board).toLowerCase().replaceAll(" ", "-")}`}>{statusFor(board)}</span><button className="icon-button moss-duplicate" aria-label={`Duplicate board ${board.name}`} title="Duplicate this board independently" disabled={creating || board.archived} onClick={e => { e.stopPropagation(); void add(board); }}><Copy size={15} /></button><button className="icon-button moss-fit-artwork" aria-label={`Fit card to artwork for ${board.name}`} title="Fit this card to the image proportions" onClick={e => { e.stopPropagation(); fitArtwork(board); }}><Maximize size={15} /></button></header>
            {isVideoBoard(board) ? <VideoCardPreview board={board} visible={visible} /> : visible ? <BoardPreview board={board} /> : <div className="moss-distant">{board.artboard.width} × {board.artboard.height} · {statusFor(board)}</div>}
            {boardErrors[board.id] || board.latest?.error ? <div className="moss-board-notice" role="status">{boardErrors[board.id] || board.latest?.error}</div> : null}
            <div className="moss-card-copy"><small>{board.artboard.width} × {board.artboard.height} · {board.regionCount} regions</small><p>{board.prompt || "Open this board to shape your first composition."}</p><small>{board.activeResult ? `${board.jobs.length ? "Previous result" : "Generated from"} r${board.activeResult.revision} · seed ${board.activeResult.seed}` : "No generated result"}{board.activeResult && board.activeResult.revision !== board.documentRevision ? ` · Draft r${board.documentRevision} has newer edits` : ""}{board.newResult ? " · New result in history" : ""}</small>{boardErrors[board.id] || board.latest?.error ? <p className="form-error">{boardErrors[board.id] || board.latest?.error}</p> : null}</div>
            <footer><small className="moss-card-meta">{board.jobs.length && board.activeResult ? `Previous result r${board.activeResult.revision}` : `${board.artboard.width} × ${board.artboard.height}`}</small><button className="secondary-button" aria-label={`Open board ${board.name}`} disabled={board.archived} onClick={e => { e.stopPropagation(); open(board); }}>Open <ArrowRight size={14} /></button><button className="primary-button" aria-label={generateLabel(board)} title={`Generate ${board.name}`} disabled={board.archived || preparingBoard(board) || Boolean(board.jobs.length)} onClick={e => { e.stopPropagation(); void generate(board); }}><Sparkles size={14} /><span>{generateLabel(board)}</span></button></footer>
          </article>;
        })}
      </div>
      {!boards.length && !query.isLoading ? <div className="moss-empty"><Layers3 size={36} /><h3>One project. Room for many ideas.</h3><p>Arrange independent MOSS or FIBO boards, then open any board to compose.</p><button className="primary-button" onClick={() => void add()}>Add your first MOSS board</button></div> : null}
    </div>
    <div className="moss-mobile-list">{visibleBoards.map(b => <article key={b.id}><button onClick={() => { setSelectedId(b.id); setPanelTab("board"); setPanelOpen(true); }}><strong>{b.name}</strong><small>{statusFor(b)} · {b.artboard.width} × {b.artboard.height}</small></button>{selectedId === b.id ? <div className="moss-mobile-artwork" style={{ aspectRatio: `${b.artboard.width} / ${b.artboard.height}` }}><BoardPreview board={b} /></div> : null}<button className="secondary-button" disabled={b.archived} onClick={() => open(b)}>Open board</button><button className="primary-button" disabled={b.archived || preparingBoard(b) || Boolean(b.jobs.length)} onClick={() => void generate(b)}>{generateLabel(b)}</button></article>)}</div>
    <CanvasUtilityPanel open={panelOpen ?? !narrow} tab={panelTab} onTabChange={value => { setPanelTab(value); setPanelOpen(true); }} onClose={() => setPanelOpen(false)} context={selected ? `Board: ${selected.name}` : "Project conversation · no board selected"} primary={boardPanel} history={historyPanel} hosts={hosts} />
    </div><footer className="canvas-footer moss-statusbar"><span>{saving ? "Saving positions…" : dirty ? "Unsaved positions" : "Workspace saved"}</span><span>{preparing.size + Object.values(editorPreparing).filter(Boolean).length} preparing · {activeJobs.filter(j => j.status === "running").length} active · {activeJobs.filter(j => j.status === "queued").length} queued · GPU capacity {query.data?.capacity ?? 1}</span></footer>
  </section>;
}
function historyReplace(url: URL) { window.history.replaceState(window.history.state, "", url); }
