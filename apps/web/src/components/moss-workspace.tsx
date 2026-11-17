"use client";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { Layers3 } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { workspacePoll } from "@/lib/live-poll";
import { canvasApi } from "@/lib/canvas-api";
import { requestBoardSetup } from "@/lib/board-setup";
import { readWorkspaceValue, rememberWorkspaceValue, useWorkspaceState } from "@/lib/workspace-session";
import { subscribeProjectRefresh } from "@/lib/project-sync";
import { mossApi, prepareBoard, fitPlacements, fitCardToArtwork, worldPoint, type Placement, type MossBoard, type BoardSettings, type ProjectWorkspace, type SelectedBoardContext, type ImageProfile, type ImageRecipeConfig, type VideoConfig } from "@/lib/moss-workspace";
import { canvasProfiles, FIBO_DEV, H3_ANIMATE, IMAGE_EDIT, MOSS, type CanvasProfile } from "@/lib/canvas-profile";
import { ASSET_MIME, acceptsImage, droppableFile, videoProfile, withImageInput, withVideoInput } from "@/lib/canvas-drop";
import { api } from "@/lib/api-client";
import { queryKeys } from "@/lib/queries";
import { assetName } from "@/lib/chat-labels";
import { loadCanvasIntent } from "@/lib/canvas-intent";
import type { CanvasContent } from "@/lib/canvas-document";
import type { Asset } from "@/lib/types";
import { CanvasEditor, type CanvasHosts } from "./canvas-workspace";
import { ImageRecipeEditor, imageRecipeDefaults, imageRecipes, isImageRecipeBoard } from "./image-recipe-board";
import { VideoBoardEditor, isVideoBoard, videoDefaults } from "./video-board";
import { CanvasUtilityPanel, useCanvasNarrow, type CanvasUtilityTab } from "./canvas-utility-panel";
import { BoardPreview } from "./canvas/board-preview";
import { BoardCard, inView } from "./canvas/board-card";
import { BoardHistory, BoardInspector, type VideoRole } from "./canvas/board-inspector";
import { BoardFinder, ToolPill } from "./canvas/tool-pill";
import { ContextMenu, type MenuItem } from "./canvas/context-menu";
import { Minimap } from "./canvas/minimap";
import { WindowBoundary } from "./desktop/window-boundary";
import { BoardPanel } from "./canvas/board-panel";
import { useBoardCamera, type Camera } from "./canvas/use-board-camera";
import { errorText, useBoardLayout } from "./canvas/use-board-layout";
import { useBoardGeneration } from "./canvas/use-board-generation";

const isField = (target: EventTarget | null) => target instanceof HTMLElement && Boolean(target.closest("input,textarea,select,[contenteditable=true]"));
type Gesture = { pointerId: number; x: number; y: number; moved: boolean } & ({ type: "pan"; camera: Camera } | { type: "board"; scale: number; placement: Placement; next: Placement });

/**
 * The project canvas: an infinite desktop of independent boards. On wide screens the
 * selected board's panel is portalled into the shell's right column (`panelHost`).
 */
export function MossWorkspace({ projectId, assets, onBoardContext, onEditingChange, panelHost, ...hosts }: CanvasHosts & { projectId: string; assets: Asset[]; onBoardContext?: (context: SelectedBoardContext | null) => void; onEditingChange?: (editing: boolean) => void; panelHost?: HTMLElement | null }) {
  const client = useQueryClient();
  const scope = `moss:${projectId}`;
  const narrow = useCanvasNarrow();
  const [panelOpen, setPanelOpen] = useState<boolean | null>(null), [panelTab, setPanelTab] = useState<CanvasUtilityTab>("board");
  const docked = Boolean(panelHost) && !narrow;
  const query = useQuery({ queryKey: ["moss-workspace", projectId], queryFn: () => mossApi.get(projectId), refetchInterval: workspacePoll });
  const engine = useQuery({ queryKey: ["canvas-engine"], queryFn: () => canvasApi.engine() });
  const [selectedId, setSelectedId] = useWorkspaceState<string | null>(`${scope}:selected`, null);
  const [openId, setOpenId] = useWorkspaceState<string | null>(`${scope}:editor`, null);
  const [error, setError] = useState(""), [creating, setCreating] = useState(false);
  const [search, setSearch] = useState(""), [hand, setHand] = useState(false), [space, setSpace] = useState(false), [archives, setArchives] = useState(false);
  const [dragged, setDragged] = useState<Placement | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; boardId: string | null; at: { x: number; y: number } } | null>(null), [dropTarget, setDropTarget] = useState<string | null>(null);
  const closeMenu = useCallback(() => setMenu(null), []);
  const initialized = useRef(false), gesture = useRef<Gesture | null>(null), suppressBoardClick = useRef(false), pointerBoard = useRef<string | null>(null);
  const { stage, attach, camera, setCamera, size, middlePanning, zoomBy } = useBoardCamera(scope, openId);
  const stageRect = () => stage.current?.getBoundingClientRect() ?? new DOMRect();
  const boards = query.data?.boards ?? [], selected = boards.find(b => b.id === selectedId), opened = boards.find(b => b.id === openId);
  const refresh = useCallback(() => { void client.invalidateQueries({ queryKey: ["moss-workspace", projectId] }); void client.invalidateQueries({ queryKey: ["canvas", projectId] }); }, [client, projectId]);
  const isEditingPosition = () => gesture.current?.type === "board" || (document.activeElement instanceof HTMLElement && Boolean(document.activeElement.closest(".moss-card-placement")));
  const layoutState = useBoardLayout({ projectId, scope, remote: query.data, boards, setError, refresh, isEditingPosition });
  const { layout, currentLayout, dirty, saving, conflict, setConflict, saveLayout, move, adopt, record, history, undoAction } = layoutState;
  const gen = useBoardGeneration({ projectId, scope, refresh, setError, onSubmit: board => setSelectedId(board.id) });
  const { setIntents } = gen;
  const selectedPlacement = layout?.present.find(p => p.boardId === selectedId);
  const visibleBoards = boards.filter(b => b.archived === archives && b.name.toLowerCase().includes(search.toLowerCase()));
  const activeJobs = boards.flatMap(b => b.jobs);

  useEffect(() => subscribeProjectRefresh(projectId, e => { if (e.full || e.types.some(t => /^(canvas\.|job\.|generation\.|asset\.)/.test(t))) refresh(); }), [projectId, refresh]);
  useEffect(() => {
    const remote = query.data;
    if (!remote || initialized.current) return;
    initialized.current = true;
    setIntents(current => { const next = { ...current }; for (const board of remote.boards) { const pending = loadCanvasIntent(projectId, board.documentId); if (pending?.boardId && pending.boardRevision) next[board.id] = { ...pending, boardId: pending.boardId, boardRevision: pending.boardRevision }; } return next; });
    try { const value = JSON.parse(localStorage.getItem(`${scope}:view`) ?? "null"); if (value?.camera?.scale >= .15 && value.camera.scale <= 2) { setCamera(value.camera); setSelectedId(value.selectedId); } } catch {}
    const params = new URLSearchParams(location.search), linked = remote.boards.find(b => b.id === params.get("board") || b.documentId === params.get("canvas"));
    if (linked) { setOpenId(linked.id); setSelectedId(linked.id); }
  }, [query.data, scope, projectId, setIntents, setCamera, setSelectedId, setOpenId]);
  useEffect(() => { if (initialized.current) localStorage.setItem(`${scope}:view`, JSON.stringify({ camera, selectedId })); }, [camera, selectedId, scope]);
  useEffect(() => {
    if (!selected) { onBoardContext?.(null); return; }
    const board = selected;
    onBoardContext?.({ boardId: board.id, documentId: board.documentId, documentRevision: board.documentRevision, boardRevision: board.revision, name: board.name, prepare: () => prepareBoard(projectId, board) });
    return () => onBoardContext?.(null);
  }, [selected, projectId, onBoardContext]);

  function adoptWorkspace(workspace: ProjectWorkspace) { client.setQueryData(["moss-workspace", projectId], workspace); adopt(workspace); }
  function fitArtwork(board: MossBoard) {
    const placement = currentLayout.current?.present.find(p => p.boardId === board.id);
    if (!placement) return;
    const image = assets.find(a => a.id === board.activeResult?.assetIds[0]);
    move(fitCardToArtwork(placement, image?.width && image.height ? { width: image.width, height: image.height } : board.artboard));
  }
  const centre = () => worldPoint({ x: size.width / 2 - 180, y: size.height / 2 - 225 }, camera);
  /** Add a board at the view centre, or with its top-left at a world point `at`. */
  async function add({ profile = MOSS, content, duplicate, at, name, image }: { profile?: CanvasProfile; content?: CanvasContent; duplicate?: MossBoard; at?: { x: number; y: number }; name?: string; image?: ImageRecipeConfig } = {}) {
    setCreating(true); setError("");
    try {
      await saveLayout();
      if (duplicate) await prepareBoard(projectId, duplicate);
      const { x, y } = at ?? centre();
      const result = await mossApi.add(projectId, { x, y, name: name ?? (duplicate ? `${duplicate.name.slice(0, 180)} copy` : profile === H3_ANIMATE ? "Untitled video" : imageRecipes.includes(profile as ImageProfile) ? "Untitled image" : "Untitled board"), duplicateBoardId: duplicate?.id, content, settings: { adapterVersion: profile, seed: null, references: [], ...(profile === H3_ANIMATE ? { video: videoDefaults() } : {}), ...(imageRecipes.includes(profile as ImageProfile) ? { image: image ?? imageRecipeDefaults(profile as ImageProfile) } : {}) } });
      adoptWorkspace(result.workspace);
      setSelectedId(result.boardId); setArchives(false); setSearch("");
    } catch (e) { setError(errorText(e)); } finally { setCreating(false); }
  }
  async function settings(board: MossBoard, next: BoardSettings, remember = true) {
    try { const saved = await mossApi.save(projectId, board, next); client.setQueryData<ProjectWorkspace>(["moss-workspace", projectId], old => old ? { ...old, boards: old.boards.map(b => b.id === saved.id ? saved : b) } : old); if (remember) record({ kind: "board", boardId: board.id, before: board.settings, after: next }); refresh(); return true; }
    catch (e) { gen.setBoardError(board.id, errorText(e)); return false; }
  }
  async function bindImageToVideo(source: MossBoard, videoTarget: string, videoRole: VideoRole) {
    const asset = assets.find(a => a.id === source.activeResult?.assetIds[0]);
    if (!asset || asset.kind !== "image") { setError("Select a completed image result first."); return; }
    await sendToVideo(asset, boards.find(b => b.id === videoTarget), videoRole, `${source.name.slice(0, 170)} video`);
  }
  /** Bind an image into a video board's mode, or start a new video board with it. */
  async function sendToVideo(asset: Asset, target: MossBoard | undefined, mode: VideoRole, name: string, at?: { x: number; y: number }) {
    try {
      const next = withVideoInput(target?.settings.video ?? videoDefaults(), asset, mode);
      if (!next.ok) throw new Error(next.reason);
      const adapterVersion = videoProfile(mode);
      if (target) { if (await settings(target, { ...target.settings, adapterVersion, video: next.value })) setSelectedId(target.id); }
      else {
        await saveLayout();
        const added = await mossApi.add(projectId, { ...(at ?? centre()), name, settings: { adapterVersion, video: next.value, seed: null, references: [] } });
        adoptWorkspace(added.workspace); setSelectedId(added.boardId);
      }
      refresh();
    } catch (error) { setError(errorText(error)); }
  }
  /**
   * An image dropped on a board that takes images becomes an input (into its open
   * draft when that has unsaved edits). Anywhere else it starts a new edit board.
   */
  async function dropAsset(asset: Asset, target: MossBoard | undefined, at: { x: number; y: number }) {
    if (asset.kind !== "image") { setError("Only images can be dropped onto the canvas for now."); return; }
    if (target && acceptsImage(target)) {
      if (isVideoBoard(target)) {
        const key = `h3:${projectId}:${target.id}:draft`, draft = readWorkspaceValue<VideoConfig>(key);
        if (draft && JSON.stringify(draft) !== JSON.stringify(target.settings.video)) {
          const next = withVideoInput(draft, asset); if (!next.ok) { setError(next.reason); return; }
          rememberWorkspaceValue(key, next.value); setSelectedId(target.id); return;
        }
        return sendToVideo(asset, target, (target.settings.video?.activeMode ?? "animate-image") as VideoRole, target.name);
      }
      const key = `image-recipe:${projectId}:${target.id}:draft`, draft = readWorkspaceValue<ImageRecipeConfig>(key), saved = target.settings.image ?? imageRecipeDefaults(IMAGE_EDIT);
      const dirty = Boolean(draft) && JSON.stringify(draft) !== JSON.stringify(saved);
      const next = withImageInput(dirty ? draft! : saved, asset); if (!next.ok) { setError(next.reason); return; }
      if (dirty) { rememberWorkspaceValue(key, next.value); setSelectedId(target.id); return; }
      if (await settings(target, { ...target.settings, adapterVersion: IMAGE_EDIT, image: next.value })) {
        if (draft) { rememberWorkspaceValue(key, next.value); rememberWorkspaceValue(`image-recipe:${projectId}:${target.id}:base`, target.revision + 1); }
        setSelectedId(target.id);
      }
      return;
    }
    const next = withImageInput(imageRecipeDefaults(IMAGE_EDIT), asset);
    if (!next.ok) { setError(next.reason); return; }
    await add({ profile: IMAGE_EDIT, image: next.value, at, name: `${assetName(asset).slice(0, 150)} edit` });
  }
  async function dropFiles(files: File[], target: MossBoard | undefined, at: { x: number; y: number }) {
    const images = files.filter(droppableFile);
    if (!images.length) { setError("Drop PNG, JPEG, WebP or GIF images."); return; }
    setCreating(true);
    try {
      for (const [index, file] of images.entries()) {
        const asset = await api.uploadAssetWithProgress(file, { project_id: projectId, role: "reference" });
        await dropAsset(asset, target, { x: at.x + index * 40, y: at.y + index * 40 });
      }
      void client.invalidateQueries({ queryKey: queryKeys.projectAssets(projectId) });
    } catch (error) { setError(errorText(error)); } finally { setCreating(false); }
  }
  async function pasteImage(at: { x: number; y: number }) {
    try {
      const items = await navigator.clipboard.read();
      const files: File[] = [];
      for (const item of items) { const type = item.types.find(t => t.startsWith("image/")); if (type) files.push(new File([await item.getType(type)], `pasted.${type.split("/")[1]}`, { type })); }
      if (!files.length) { setError("The clipboard has no image to paste."); return; }
      await dropFiles(files, undefined, at);
    } catch { setError("Darius could not read the clipboard. Drop the image file onto the canvas instead."); }
  }
  function jump(board: MossBoard) {
    setSelectedId(board.id); setArchives(board.archived);
    const placement = layout?.present.find(p => p.boardId === board.id);
    if (placement) setCamera(fitPlacements([placement], size));
  }
  /** Tween the camera; the canvas stays live underneath an open board. */
  const flight = useRef(0);
  function flyTo(target: Camera, ms = 340) {
    const from = camera, id = ++flight.current;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setCamera(target); return; }
    let start: number | null = null;
    const step = (now: number) => {
      if (id !== flight.current) return;
      start ??= now;
      const t = Math.min(1, (now - start) / ms), e = 1 - Math.pow(1 - t, 3);
      setCamera({ x: from.x + (target.x - from.x) * e, y: from.y + (target.y - from.y) * e, scale: from.scale + (target.scale - from.scale) * e });
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  // Where the open board's card sat on screen, and the camera to return to.
  const [grown, setGrown] = useState<string | null>(null);
  const [zoom, setZoom] = useState<{ origin: { x: number; y: number; width: number; height: number }; before: Camera } | null>(null);
  function open(board: MossBoard) {
    setSelectedId(board.id); if (board.archived) return;
    setGrown(null);
    const placement = layout?.present.find(p => p.boardId === board.id);
    if (placement) {
      setZoom({ origin: { x: placement.x * camera.scale + camera.x, y: placement.y * camera.scale + camera.y, width: placement.displayWidth * camera.scale, height: placement.displayHeight * camera.scale }, before: camera });
      flyTo(fitPlacements([placement], size));
    } else setZoom(null);
    setOpenId(board.id);
    const url = new URL(location.href); url.searchParams.delete("canvas"); url.searchParams.set("board", board.id); historyReplace(url);
  }
  function closeEditor() {
    if (opened) void prepareBoard(projectId, opened).catch(e => gen.setBoardError(opened.id, errorText(e)));
    setOpenId(null);
    if (zoom) flyTo(zoom.before);
    const url = new URL(location.href); url.searchParams.delete("board"); url.searchParams.delete("canvas"); historyReplace(url); refresh();
  }
  async function reloadPositions() {
    if (!confirm("Reload saved positions? Your position draft will be discarded; board documents are unchanged.")) return;
    try { const response = await query.refetch(); if (!response.data || response.isError) throw new Error("Saved positions could not load; your draft is retained."); adopt(response.data); layoutState.clearHistory(); setConflict(false); setError(""); }
    catch (error) { setError(errorText(error)); }
  }
  function exportPositions() { const blob = new Blob([JSON.stringify(layout?.present, null, 2)], { type: "application/json" }), a = document.createElement("a"), url = URL.createObjectURL(blob); a.href = url; a.download = "workspace-position-draft.json"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }

  const pointAt = (clientX: number, clientY: number) => { const rect = stageRect(); return worldPoint({ x: clientX - rect.left, y: clientY - rect.top }, camera); };
  const menuBoard = boards.find(b => b.id === menu?.boardId);
  const menuItems: MenuItem[] = !menu ? [] : menuBoard ? [
    { label: "Open", hint: "Double-click", onSelect: () => open(menuBoard), disabled: menuBoard.archived },
    { label: gen.generateLabel(menuBoard), onSelect: () => void gen.generate(menuBoard), disabled: !gen.canGenerate(menuBoard) },
    { label: "Duplicate", onSelect: () => void add({ duplicate: menuBoard }), disabled: creating || menuBoard.archived },
    { separator: true },
    { label: "Animate this image", hint: "New video board", onSelect: () => void bindImageToVideo(menuBoard, "new", "animate-image"), disabled: !assets.some(a => a.id === menuBoard.activeResult?.assetIds[0] && a.kind === "image") },
    { label: "Fit card to artwork", onSelect: () => fitArtwork(menuBoard) },
    { label: "Fit view to this board", onSelect: () => jump(menuBoard) },
    { separator: true },
    { label: menuBoard.archived ? "Restore to workspace" : "Archive", danger: !menuBoard.archived, onSelect: async () => { if (!confirm(menuBoard.archived ? "Restore this board?" : "Archive this board? Its document, assets and pending jobs are retained.")) return; try { await mossApi.save(projectId, menuBoard, menuBoard.settings, !menuBoard.archived); refresh(); setSelectedId(null); } catch (e) { setError(errorText(e)); } } },
  ] : [
    { separator: true, label: "New board here" },
    { label: "MOSS board", hint: "Regions → one composition", onSelect: () => void add({ at: menu.at }) },
    { label: "FIBO board", hint: "Regions with palettes", onSelect: () => void add({ profile: FIBO_DEV, at: menu.at }) },
    ...imageRecipes.map(profile => ({ label: canvasProfiles[profile].name, hint: "Image board", onSelect: () => void add({ profile, at: menu.at }) })),
    { label: "Video board", hint: "MiniMax H3", onSelect: () => void add({ profile: H3_ANIMATE, at: menu.at }) },
    { separator: true },
    { label: "Paste image", hint: "Ctrl+V", onSelect: () => void pasteImage(menu.at) },
    { label: "Fit all boards", onSelect: () => setCamera(fitPlacements(layout?.present.filter(p => visibleBoards.some(b => b.id === p.boardId)) ?? [], size)) },
  ];
  const inspectorProps = (board: MossBoard | undefined) => ({ status: board ? gen.statusFor(board) : "", error: board ? gen.errorFor(board) : "", generateLabel: board ? gen.generateLabel(board) : "", canGenerate: board ? gen.canGenerate(board) : false, preparing: board ? gen.preparingBoard(board) : false });
  const guard = (title: string, node: React.ReactNode) => <WindowBoundary key={selectedId ?? "none"} title={title} onClose={() => setSelectedId(null)} closeLabel="Deselect board">{node}</WindowBoundary>;
  const boardPanel = guard("This board's settings", <BoardInspector projectId={projectId} selected={selected} boards={boards} assets={assets} placement={selectedPlacement} creating={creating} {...inspectorProps(selected)}
    onSettings={(board, next) => settings(board, next)} onOpen={open} onGenerate={board => void gen.generate(board)} onDuplicate={board => void add({ duplicate: board })} onMove={move} onFitArtwork={fitArtwork} onJump={jump}
    onBindVideo={(board, target, role) => void bindImageToVideo(board, target, role)} onArchived={() => setSelectedId(null)} setError={setError} setBoardError={gen.setBoardError} refresh={refresh} />);
  const historyPanel = guard("This board's history", <BoardHistory projectId={projectId} selected={selected} setError={setError} refresh={refresh} />);

  const editing = opened && !opened.archived ? opened : null;
  const editor = !editing ? null : isImageRecipeBoard(editing) ? <ImageRecipeEditor key={editing.id} board={editing} projectId={projectId} assets={assets} onExit={closeEditor} onGenerate={() => gen.generate(editing)} onVideo={() => void bindImageToVideo(editing, "new", "animate-image")} {...hosts} />
    : isVideoBoard(editing) ? <VideoBoardEditor key={editing.id} board={editing} projectId={projectId} assets={assets} onExit={closeEditor} onGenerate={() => gen.generate(editing)} {...hosts} />
    : <CanvasEditor key={`${projectId}:${editing.documentId}`} projectId={projectId} documentId={editing.documentId} assets={assets} {...hosts} chooser={null} presets={engine.data?.presets ?? []} onExit={closeEditor} board={editing} />;
  const origin = zoom?.origin ?? null;
  const editingId = editing?.id ?? null;
  useEffect(() => { onEditingChange?.(Boolean(editingId)); }, [editingId, onEditingChange]);
  // Esc zooms back out when nothing inside the editor claimed it (the editor stops
  // propagation when it closes its own panels first).
  const close = useRef(closeEditor);
  useLayoutEffect(() => { close.current = closeEditor; });
  useEffect(() => {
    if (!editingId) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || isField(event.target) || document.querySelector("[role=dialog][aria-modal=true]")) return;
      close.current();
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [editingId]);
  const editorLayer = <AnimatePresence>{editing ? <motion.div key={editing.id} className="board-zoom-layer" aria-label={`${editing.name} editor`} role="group"
    initial={origin ? { x: origin.x, y: origin.y, width: origin.width, height: origin.height, opacity: .4, borderRadius: 22 } : false}
    animate={{ x: 0, y: 0, width: size.width, height: size.height, opacity: 1, borderRadius: 26 }}
    exit={origin ? { x: origin.x, y: origin.y, width: origin.width, height: origin.height, opacity: 0, borderRadius: 22 } : { opacity: 0 }}
    transition={{ type: "spring", stiffness: 260, damping: 32, mass: .9 }} onAnimationComplete={() => setGrown(editing.id)}>
    {/* The editor mounts once the layer is full size, so it measures the real space. */}
    {grown === editing.id || !origin ? <WindowBoundary title={editing.name} onClose={closeEditor} closeLabel="Back to the canvas">{editor}</WindowBoundary> : <div className="board-zoom-preview"><BoardPreview board={editing} large /></div>}
  </motion.div> : null}</AnimatePresence>;
  return <><section className="canvas-workspace moss-workspace canvas-refined" aria-label="MOSS board workspace" tabIndex={0} inert={Boolean(editing)} aria-hidden={editing ? true : undefined} onKeyDown={e => {
    if (isField(e.target)) return;
    if (e.code === "Space") { e.preventDefault(); setSpace(true); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); void undoAction(e.shiftKey); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") { e.preventDefault(); const rect = stageRect(); void pasteImage(worldPoint({ x: rect.width / 2 - 180, y: rect.height / 2 - 225 }, camera)); return; }
    if (!e.ctrlKey && !e.metaKey && !e.altKey && e.key.toLowerCase() === "v") setHand(false);
    if (!e.ctrlKey && !e.metaKey && !e.altKey && e.key.toLowerCase() === "h") setHand(true);
    if (e.key === "Escape") { if (hosts.assistantOpen) hosts.onToggleAssistant?.(); else if (docked && selectedId) setSelectedId(null); }
  }} onKeyUp={e => { if (e.code === "Space") setSpace(false); }} onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) setSpace(false); }}>
    <BoardFinder boards={boards} selectedId={selectedId} search={search} archives={archives} onSearch={setSearch} onJump={jump} onToggleArchives={() => setArchives(v => !v)} />
    {(error || query.isError) ? <div className="canvas-notice is-error" role="alert">{error || (query.data ? "Status updates are interrupted. Last known results are shown; retry to reconnect." : "Workspace could not load")}
      {conflict ? <><button onClick={exportPositions}>Export positions</button><button onClick={() => void reloadPositions()}>Reload positions</button></> : <button onClick={() => { setError(""); refresh(); }}>Retry</button>}</div> : null}

    <div className="moss-body"><div className={`moss-stage ${hand || space ? "is-panning" : ""} ${middlePanning ? "is-middle-panning" : ""}`} ref={attach} tabIndex={-1} data-scale={camera.scale} data-pan-x={camera.x} data-pan-y={camera.y}
      style={{ "--pan-x": `${camera.x}px`, "--pan-y": `${camera.y}px`, "--zoom": camera.scale } as CSSProperties}
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
      onPointerUp={e => { const g = gesture.current; if (!g || g.pointerId !== e.pointerId) return; if (g.type === "board" && g.moved) move(g.next); else if (g.type === "board") setPanelOpen(true); else if (!g.moved && docked) setSelectedId(null); gesture.current = null; setDragged(null); }}
      onPointerCancel={() => { gesture.current = null; setDragged(null); }} onLostPointerCapture={() => { gesture.current = null; setDragged(null); }}
      onClickCapture={e => { if (suppressBoardClick.current) { e.preventDefault(); e.stopPropagation(); } }}
      onDragOver={e => { if (e.dataTransfer.types.includes(ASSET_MIME) || e.dataTransfer.types.includes("Files")) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; const id = (e.target as Element).closest<HTMLElement>(".moss-board")?.dataset.boardId ?? null; if (id !== dropTarget) setDropTarget(id); } }}
      onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDropTarget(null); }}
      onDrop={e => {
        e.preventDefault(); setDropTarget(null);
        const target = boards.find(b => b.id === (e.target as Element).closest<HTMLElement>(".moss-board")?.dataset.boardId), at = pointAt(e.clientX, e.clientY);
        const assetId = e.dataTransfer.getData(ASSET_MIME), asset = assets.find(a => a.id === assetId);
        if (asset) void dropAsset(asset, target, at); else if (e.dataTransfer.files.length) void dropFiles([...e.dataTransfer.files], target, at);
      }}
      onContextMenu={e => {
        if ((e.target as Element).closest("input,textarea,select")) return;
        e.preventDefault();
        const rect = e.currentTarget.getBoundingClientRect(), boardId = (e.target as Element).closest<HTMLElement>(".moss-board")?.dataset.boardId ?? null;
        if (boardId) setSelectedId(boardId);
        setMenu({ x: e.clientX - rect.left, y: e.clientY - rect.top, boardId, at: pointAt(e.clientX, e.clientY) });
      }}
      onDoubleClick={e => { if (suppressBoardClick.current || (e.target as Element).closest("button,video,a")) return; const board = boards.find(b => b.id === pointerBoard.current); if (board) open(board); }}>
      <div className="moss-world" style={{ transform: `translate(${camera.x}px,${camera.y}px) scale(${camera.scale})` }}>
        <svg className="moss-edges" aria-hidden="true">{boards.filter(b => !b.archived).flatMap(target => target.settings.references.map(ref => {
          const a = layout?.present.find(p => p.boardId === ref.sourceBoardId), b = layout?.present.find(p => p.boardId === target.id); if (!a || !b) return null;
          const from = { x: a.x + a.displayWidth, y: a.y + a.displayHeight / 2 }, to = { x: b.x, y: b.y + b.displayHeight / 2 };
          return <g key={`${target.id}:${ref.id}`} className="moss-edge"><path d={`M ${from.x} ${from.y} C ${from.x + 100} ${from.y}, ${to.x - 100} ${to.y}, ${to.x} ${to.y}`} /><circle cx={from.x} cy={from.y} r={5} /><circle cx={to.x} cy={to.y} r={5} /></g>;
        }))}</svg>
        {visibleBoards.map(board => {
          const placement = dragged?.boardId === board.id ? dragged : layout?.present.find(p => p.boardId === board.id); if (!placement) return null;
          return <BoardCard key={board.id} board={board} placement={placement} scale={camera.scale} visible={inView(placement, camera, size)} selected={selectedId === board.id} dropTarget={dropTarget === board.id} dragging={dragged?.boardId === board.id}
            busy={gen.preparingBoard(board) || Boolean(board.jobs.length)} status={gen.statusFor(board)} error={gen.errorFor(board)} generateLabel={gen.generateLabel(board)} canGenerate={gen.canGenerate(board)} creating={creating}
            onSelect={() => setSelectedId(board.id)} onDuplicate={() => void add({ duplicate: board })} onFitArtwork={() => fitArtwork(board)} onOpen={() => open(board)} onGenerate={() => void gen.generate(board)} />;
        })}
      </div>
      {menu ? <ContextMenu x={menu.x} y={menu.y} label={menuBoard ? `${menuBoard.name} actions` : "Canvas actions"} items={menuItems} onClose={closeMenu} /> : null}
      {!boards.length && !query.isLoading ? <div className="moss-empty"><Layers3 size={36} /><h3>One project. Room for many ideas.</h3><p>Arrange independent MOSS or FIBO boards, then open any board to compose. Drop images here, or right-click to add a board.</p><button className="primary-button" onClick={() => void add()}>Add your first MOSS board</button></div> : null}
    </div>
    <div className="moss-mobile-list">{visibleBoards.map(b => <article key={b.id}><button onClick={() => { setSelectedId(b.id); setPanelTab("board"); setPanelOpen(true); }}><strong>{b.name}</strong><small>{gen.statusFor(b)} · {b.artboard.width} × {b.artboard.height}</small></button>{selectedId === b.id ? <div className="moss-mobile-artwork" style={{ aspectRatio: `${b.artboard.width} / ${b.artboard.height}` }}><BoardPreview board={b} /></div> : null}<button className="secondary-button" disabled={b.archived} onClick={() => open(b)}>Open board</button><button className="primary-button" disabled={!gen.canGenerate(b)} onClick={() => void gen.generate(b)}>{gen.generateLabel(b)}</button></article>)}</div>
    {docked ? createPortal(selected && !editing ? <BoardPanel name={selected.name} tab={panelTab === "history" ? "history" : "board"} onTab={setPanelTab} onClose={() => setSelectedId(null)} board={boardPanel} history={historyPanel} /> : null, panelHost!)
      : <CanvasUtilityPanel open={panelOpen ?? !narrow} tab={panelTab} onTabChange={value => { setPanelTab(value); setPanelOpen(true); }} onClose={() => setPanelOpen(false)} context={selected ? `Board: ${selected.name}` : "Project conversation · no board selected"} primary={boardPanel} history={historyPanel} hosts={hosts} />}
    </div>
    {layout?.present.length ? <Minimap placements={layout.present.filter(p => visibleBoards.some(b => b.id === p.boardId))} camera={camera} size={size} selectedId={selectedId} busyIds={new Set(boards.filter(b => b.jobs.length).map(b => b.id))} onCamera={setCamera} /> : null}
    <ToolPill hand={hand} canUndo={Boolean(history.past.length)} canRedo={Boolean(history.future.length)} scale={camera.scale} creating={creating} canPrepare={Boolean(selected)}
      onHand={setHand} onUndo={() => void undoAction(false)} onRedo={() => void undoAction(true)} onZoom={zoomBy}
      onFitAll={() => setCamera(fitPlacements(layout?.present.filter(p => visibleBoards.some(b => b.id === p.boardId)) ?? [], size))}
      onAdd={(profile, content) => void add({ profile, content })} onImportError={setError}
      onPrepare={() => { if (selected) void requestBoardSetup(selected.settings.adapterVersion).catch(error => setError(errorText(error))); }} />
    <footer className="dk-canvas-status" role="status"><span>{saving ? "Saving positions…" : dirty ? "Unsaved positions" : "Workspace saved"}</span><span>{gen.preparingCount} preparing · {activeJobs.filter(j => j.status === "running").length} active · {activeJobs.filter(j => j.status === "queued").length} queued · GPU capacity {query.data?.capacity ?? 1}</span></footer>
  </section>{editorLayer}</>;
}
function historyReplace(url: URL) { window.history.replaceState(window.history.state, "", url); }
