"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Layers3 } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { workspacePoll } from "@/lib/live-poll";
import { canvasApi } from "@/lib/canvas-api";
import { requestBoardSetup } from "@/lib/board-setup";
import { useWorkspaceState } from "@/lib/workspace-session";
import { subscribeProjectRefresh } from "@/lib/project-sync";
import { useDariusStore } from "@/lib/store";
import { mossApi, prepareBoard, fitPlacements, fitCardToArtwork, worldPoint, type Placement, type MossBoard, type BoardSettings, type ProjectWorkspace, type SelectedBoardContext, type ImageProfile } from "@/lib/moss-workspace";
import { H3_ANIMATE, MOSS, type CanvasProfile } from "@/lib/canvas-profile";
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
import { WorkspaceToolbar } from "./canvas/workspace-toolbar";
import { useBoardCamera, type Camera } from "./canvas/use-board-camera";
import { errorText, useBoardLayout } from "./canvas/use-board-layout";
import { useBoardGeneration } from "./canvas/use-board-generation";

const isField = (target: EventTarget | null) => target instanceof HTMLElement && Boolean(target.closest("input,textarea,select,[contenteditable=true]"));
type Gesture = { pointerId: number; x: number; y: number; moved: boolean } & ({ type: "pan"; camera: Camera } | { type: "board"; scale: number; placement: Placement; next: Placement });

export function MossWorkspace({ projectId, assets, onBoardContext, expanded = false, onToggleExpanded, onExitWorkspace, ...hosts }: CanvasHosts & { projectId: string; assets: Asset[]; onBoardContext?: (context: SelectedBoardContext | null) => void; expanded?: boolean; onToggleExpanded?: () => void; onExitWorkspace?: () => void }) {
  const client = useQueryClient(), projectName = useDariusStore(s => s.projects.find(p => p.id === projectId)?.name ?? "Project");
  const scope = `moss:${projectId}`;
  const narrow = useCanvasNarrow();
  const [panelOpen, setPanelOpen] = useState<boolean | null>(null), [panelTab, setPanelTab] = useState<CanvasUtilityTab>("board");
  const query = useQuery({ queryKey: ["moss-workspace", projectId], queryFn: () => mossApi.get(projectId), refetchInterval: workspacePoll });
  const engine = useQuery({ queryKey: ["canvas-engine"], queryFn: () => canvasApi.engine() });
  const [selectedId, setSelectedId] = useWorkspaceState<string | null>(`${scope}:selected`, null);
  const [openId, setOpenId] = useWorkspaceState<string | null>(`${scope}:editor`, null);
  const [error, setError] = useState(""), [creating, setCreating] = useState(false);
  const [search, setSearch] = useState(""), [hand, setHand] = useState(false), [space, setSpace] = useState(false), [archives, setArchives] = useState(false);
  const [dragged, setDragged] = useState<Placement | null>(null);
  const initialized = useRef(false), gesture = useRef<Gesture | null>(null), suppressBoardClick = useRef(false), pointerBoard = useRef<string | null>(null);
  const { attach, camera, setCamera, size, middlePanning, zoomBy } = useBoardCamera(scope, openId);
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
  async function add({ profile = MOSS, content, duplicate }: { profile?: CanvasProfile; content?: CanvasContent; duplicate?: MossBoard } = {}) {
    setCreating(true); setError("");
    try {
      await saveLayout();
      if (duplicate) await prepareBoard(projectId, duplicate);
      const { x, y } = centre();
      const result = await mossApi.add(projectId, { x, y, name: duplicate ? `${duplicate.name.slice(0, 180)} copy` : profile === H3_ANIMATE ? "Untitled video" : imageRecipes.includes(profile as ImageProfile) ? "Untitled image" : "Untitled board", duplicateBoardId: duplicate?.id, content, settings: { adapterVersion: profile, seed: null, references: [], ...(profile === H3_ANIMATE ? { video: videoDefaults() } : {}), ...(imageRecipes.includes(profile as ImageProfile) ? { image: imageRecipeDefaults(profile as ImageProfile) } : {}) } });
      adoptWorkspace(result.workspace);
      setSelectedId(result.boardId); setArchives(false); setSearch("");
    } catch (e) { setError(errorText(e)); } finally { setCreating(false); }
  }
  async function settings(board: MossBoard, next: BoardSettings, remember = true) {
    try { const saved = await mossApi.save(projectId, board, next); client.setQueryData<ProjectWorkspace>(["moss-workspace", projectId], old => old ? { ...old, boards: old.boards.map(b => b.id === saved.id ? saved : b) } : old); if (remember) record({ kind: "board", boardId: board.id, before: board.settings, after: next }); refresh(); return true; }
    catch (e) { gen.setBoardError(board.id, errorText(e)); return false; }
  }
  async function bindImageToVideo(source: MossBoard, videoTarget: string, videoRole: VideoRole) {
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
        const added = await mossApi.add(projectId, { ...centre(), name: `${source.name.slice(0,170)} video`, settings: { adapterVersion, video: config, seed: null, references: [] } });
        adoptWorkspace(added.workspace); setSelectedId(added.boardId);
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
  function closeEditor() { if (opened) void prepareBoard(projectId, opened).catch(e => gen.setBoardError(opened.id, errorText(e))); setOpenId(null); const url = new URL(location.href); url.searchParams.delete("board"); url.searchParams.delete("canvas"); historyReplace(url); refresh(); }
  async function reloadPositions() {
    if (!confirm("Reload saved positions? Your position draft will be discarded; board documents are unchanged.")) return;
    try { const response = await query.refetch(); if (!response.data || response.isError) throw new Error("Saved positions could not load; your draft is retained."); adopt(response.data); layoutState.clearHistory(); setConflict(false); setError(""); }
    catch (error) { setError(errorText(error)); }
  }
  function exportPositions() { const blob = new Blob([JSON.stringify(layout?.present, null, 2)], { type: "application/json" }), a = document.createElement("a"), url = URL.createObjectURL(blob); a.href = url; a.download = "workspace-position-draft.json"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }

  const inspectorProps = (board: MossBoard | undefined) => ({ status: board ? gen.statusFor(board) : "", error: board ? gen.errorFor(board) : "", generateLabel: board ? gen.generateLabel(board) : "", canGenerate: board ? gen.canGenerate(board) : false, preparing: board ? gen.preparingBoard(board) : false });
  const boardPanel = <BoardInspector projectId={projectId} selected={selected} boards={boards} assets={assets} placement={selectedPlacement} creating={creating} {...inspectorProps(selected)}
    onSettings={(board, next) => settings(board, next)} onOpen={open} onGenerate={board => void gen.generate(board)} onDuplicate={board => void add({ duplicate: board })} onMove={move} onFitArtwork={fitArtwork} onJump={jump}
    onBindVideo={(board, target, role) => void bindImageToVideo(board, target, role)} onArchived={() => setSelectedId(null)} setError={setError} setBoardError={gen.setBoardError} refresh={refresh} />;
  const historyPanel = <BoardHistory projectId={projectId} selected={selected} setError={setError} refresh={refresh} />;

  if (opened && !opened.archived && isImageRecipeBoard(opened)) return <ImageRecipeEditor key={opened.id} board={opened} projectId={projectId} assets={assets} onExit={closeEditor} onGenerate={() => gen.generate(opened)} onVideo={() => void bindImageToVideo(opened, "new", "animate-image")} {...hosts} />;
  if (opened && !opened.archived && isVideoBoard(opened)) return <VideoBoardEditor key={opened.id} board={opened} projectId={projectId} assets={assets} onExit={closeEditor} onGenerate={() => gen.generate(opened)} {...hosts} />;
  if (opened && !opened.archived) return <CanvasEditor key={`${projectId}:${opened.documentId}`} projectId={projectId} documentId={opened.documentId} assets={assets} {...hosts} chooser={null} presets={engine.data?.presets ?? []} onExit={closeEditor} board={opened} />;
  return <section className="canvas-workspace moss-workspace canvas-refined" aria-label="MOSS board workspace" tabIndex={0} onKeyDown={e => {
    if (isField(e.target)) return;
    if (e.code === "Space") { e.preventDefault(); setSpace(true); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); void undoAction(e.shiftKey); }
    if (e.key === "Escape" && hosts.assistantOpen) { hosts.onToggleAssistant?.(); }
  }} onKeyUp={e => { if (e.code === "Space") setSpace(false); }} onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) setSpace(false); }}>
    <WorkspaceToolbar projectName={projectName} boards={boards} selectedId={selectedId} search={search} archives={archives} creating={creating} hand={hand}
      canUndo={Boolean(history.past.length)} canRedo={Boolean(history.future.length)} scale={camera.scale} panelExpanded={(panelOpen ?? !narrow) || Boolean(hosts.assistantOpen)} expanded={expanded}
      onSearch={setSearch} onJump={jump} onToggleArchives={() => setArchives(v => !v)} onAdd={(profile, content) => void add({ profile, content })} onImportError={setError}
      onPrepare={() => { if (selected) void requestBoardSetup(selected.settings.adapterVersion).catch(error => setError(errorText(error))); }}
      onHand={setHand} onUndo={() => void undoAction(false)} onRedo={() => void undoAction(true)} onZoom={zoomBy} onTogglePanel={() => setPanelOpen(value => !(value ?? !narrow))}
      onFitAll={() => setCamera(fitPlacements(layout?.present.filter(p => visibleBoards.some(b => b.id === p.boardId)) ?? [], size))} onExit={onExitWorkspace} onToggleExpanded={onToggleExpanded} />
    {(error || query.isError) ? <div className="canvas-notice is-error" role="alert">{error || (query.data ? "Status updates are interrupted. Last known results are shown; retry to reconnect." : "Workspace could not load")}
      {conflict ? <><button onClick={exportPositions}>Export positions</button><button onClick={() => void reloadPositions()}>Reload positions</button></> : <button onClick={() => { setError(""); refresh(); }}>Retry</button>}</div> : null}

    <div className="moss-body"><div className={`moss-stage ${hand || space ? "is-panning" : ""} ${middlePanning ? "is-middle-panning" : ""}`} ref={attach} tabIndex={-1} data-scale={camera.scale} data-pan-x={camera.x} data-pan-y={camera.y}
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
      onClickCapture={e => { if (suppressBoardClick.current) { e.preventDefault(); e.stopPropagation(); } }}
      onDoubleClick={e => { if (suppressBoardClick.current || (e.target as Element).closest("button,video,a")) return; const board = boards.find(b => b.id === pointerBoard.current); if (board) open(board); }}>
      <div className="moss-world" style={{ transform: `translate(${camera.x}px,${camera.y}px) scale(${camera.scale})` }}>
        <svg className="moss-edges" aria-hidden="true">{boards.filter(b => !b.archived).flatMap(target => target.settings.references.map(ref => { const a = layout?.present.find(p => p.boardId === ref.sourceBoardId), b = layout?.present.find(p => p.boardId === target.id); if (!a || !b) return null; return <path key={`${target.id}:${ref.id}`} d={`M ${a.x + a.displayWidth} ${a.y + a.displayHeight/2} C ${a.x + a.displayWidth+100} ${a.y+a.displayHeight/2}, ${b.x-100} ${b.y+b.displayHeight/2}, ${b.x} ${b.y+b.displayHeight/2}`} />; }))}</svg>
        {visibleBoards.map(board => {
          const placement = dragged?.boardId === board.id ? dragged : layout?.present.find(p => p.boardId === board.id); if (!placement) return null;
          return <BoardCard key={board.id} board={board} placement={placement} scale={camera.scale} visible={inView(placement, camera, size)} selected={selectedId === board.id} dragging={dragged?.boardId === board.id}
            busy={gen.preparingBoard(board) || Boolean(board.jobs.length)} status={gen.statusFor(board)} error={gen.errorFor(board)} generateLabel={gen.generateLabel(board)} canGenerate={gen.canGenerate(board)} creating={creating}
            onSelect={() => setSelectedId(board.id)} onDuplicate={() => void add({ duplicate: board })} onFitArtwork={() => fitArtwork(board)} onOpen={() => open(board)} onGenerate={() => void gen.generate(board)} />;
        })}
      </div>
      {!boards.length && !query.isLoading ? <div className="moss-empty"><Layers3 size={36} /><h3>One project. Room for many ideas.</h3><p>Arrange independent MOSS or FIBO boards, then open any board to compose.</p><button className="primary-button" onClick={() => void add()}>Add your first MOSS board</button></div> : null}
    </div>
    <div className="moss-mobile-list">{visibleBoards.map(b => <article key={b.id}><button onClick={() => { setSelectedId(b.id); setPanelTab("board"); setPanelOpen(true); }}><strong>{b.name}</strong><small>{gen.statusFor(b)} · {b.artboard.width} × {b.artboard.height}</small></button>{selectedId === b.id ? <div className="moss-mobile-artwork" style={{ aspectRatio: `${b.artboard.width} / ${b.artboard.height}` }}><BoardPreview board={b} /></div> : null}<button className="secondary-button" disabled={b.archived} onClick={() => open(b)}>Open board</button><button className="primary-button" disabled={!gen.canGenerate(b)} onClick={() => void gen.generate(b)}>{gen.generateLabel(b)}</button></article>)}</div>
    <CanvasUtilityPanel open={panelOpen ?? !narrow} tab={panelTab} onTabChange={value => { setPanelTab(value); setPanelOpen(true); }} onClose={() => setPanelOpen(false)} context={selected ? `Board: ${selected.name}` : "Project conversation · no board selected"} primary={boardPanel} history={historyPanel} hosts={hosts} />
    </div><footer className="canvas-footer moss-statusbar"><span>{saving ? "Saving positions…" : dirty ? "Unsaved positions" : "Workspace saved"}</span><span>{gen.preparingCount} preparing · {activeJobs.filter(j => j.status === "running").length} active · {activeJobs.filter(j => j.status === "queued").length} queued · GPU capacity {query.data?.capacity ?? 1}</span></footer>
  </section>;
}
function historyReplace(url: URL) { window.history.replaceState(window.history.state, "", url); }
