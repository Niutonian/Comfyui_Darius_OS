"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, Download, Film, FolderOpen, LoaderCircle, MessageSquare, PanelRightClose, PanelRightOpen, Plus, Redo2, Save, Scissors, Search, Sparkles, Trash2, Undo2, Volume2, VolumeX, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api-client";
import { queryKeys, useTimelines, useTimelineVersions } from "@/lib/queries";
import { useDariusStore } from "@/lib/store";
import { assetName, pictureClips, previewIssue, reflowClips, removeClip, sequenceDuration, splitClip, trimClip } from "@/lib/edit-timeline";
import { useTimelineDraft } from "@/lib/use-timeline-draft";
import { dragTrim, moveClipTo } from "@/lib/timeline-motion";
import { editShortcut } from "@/lib/edit-shortcuts";
import { TimelineStrip } from "./timeline-strip";
import { RenderJobStatus } from "./render-job-status";
import type { Asset, ShotBoardEntry, TimelineClip, TimelineTrack, TimelineVersion } from "@/lib/types";
import { MediaPreview } from "./media-preview";
import { EmptyState, LoadingState } from "./states";
import { EditThumbnail } from "./edit-thumbnail";
import { editClock, SequencePlayer } from "./sequence-player";
import { useWorkspaceState } from "@/lib/workspace-session";

type DeskOptions = { assistantOpen?: boolean; onToggleAssistant?: () => void; onAssistantHost?: (host: HTMLDivElement | null) => void; onComposerHost?: (host: HTMLDivElement | null) => void };
function normalizeTracks(version?: TimelineVersion): TimelineTrack[] {
  if (!version) return [{ kind: "video", clips: [] }, { kind: "audio", clips: [] }];
  return version.tracks.map((raw, index) => {
    const track = raw as { kind?: string; clips?: Array<Record<string, unknown>> };
    return { ...track, kind: track.kind ?? `track-${index + 1}`, clips: (track.clips ?? []).map((clip, i) => ({ ...clip, id: String(clip.id ?? `clip-${index}-${i}`), timeline_in: Number(clip.timeline_in ?? 0), timeline_out: Number(clip.timeline_out ?? 0) })) as TimelineClip[] };
  });
}

export function DirectorDesk({ assets, assistantOpen, onToggleAssistant, onAssistantHost, onComposerHost }: { assets: Asset[] } & DeskOptions) {
  const projectId = useDariusStore((state) => state.activeProjectId);
  const [chosenId, setChosenId] = useWorkspaceState(`edit:${projectId}:timeline`, "");
  const timelines = useTimelines(projectId);
  const timeline = timelines.data?.find((item) => item.id === chosenId) ?? timelines.data?.[0];
  if (!chosenId && timeline) setChosenId(timeline.id);
  const versions = useTimelineVersions(timeline?.id ?? null);
  const latest = useMemo(() => [...(versions.data ?? [])].sort((a, b) => b.version_number - a.version_number)[0], [versions.data]);
  const board = useQuery({ queryKey: ["shot-board", projectId], queryFn: () => api.shotBoard(projectId!), enabled: Boolean(projectId) });
  const client = useQueryClient();
  const create = useMutation({
    mutationFn: () => api.createTimeline({ project_id: projectId!, name: "Project assembly" }),
    onSuccess: (created) => { setChosenId(created.id); void client.invalidateQueries({ queryKey: queryKeys.timelines(projectId!) }); },
  });
  const propose = useMutation({
    mutationFn: () => api.proposeTimeline(timeline!.id, timeline!.scene_id),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.timelineVersions(timeline!.id) }),
  });
  const error = timelines.error || versions.error || create.error || propose.error;
  if (!projectId) return <div className="view edit-view director-desk"><EmptyState title="Choose a project to edit" description="Your shots, takes and saved cuts stay together in one project." /></div>;
  if (timelines.isLoading) return <div className="view edit-view director-desk"><LoadingState label="Loading your editing desk…" /></div>;
  return <div className="view edit-view director-desk">
    <header className="desk-heading"><div><span className="eyebrow">Director’s desk</span><h1>Your next cut.</h1></div><div className="desk-heading-actions">{timeline ? <label className="desk-sequence-select"><span className="sr-only">Timeline</span><select aria-label="Timeline" value={timeline.id} onChange={(event) => { if (event.target.value !== timeline.id && !window.confirm("Switch timelines? Save any unsaved cut first.")) return; setChosenId(event.target.value); }}>{timelines.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : null}{timeline ? <button className="secondary-button" type="button" disabled={propose.isPending} onClick={() => propose.mutate()}><Sparkles size={15} />{propose.isPending ? "Proposing…" : "Propose from shots"}</button> : <button className="primary-button" type="button" disabled={create.isPending} onClick={() => create.mutate()}><Plus size={15} />Create timeline</button>}<button className="secondary-button" type="button" aria-label="Toggle Darius assistant" aria-pressed={Boolean(assistantOpen)} onClick={onToggleAssistant} disabled={!onToggleAssistant}><MessageSquare size={15} />Darius</button></div></header>
    {error ? <p className="form-error edit-notice" role="alert">{error instanceof Error ? error.message : "The timeline could not be loaded."}</p> : null}
    {!timeline ? <EmptyState title="Make room for your story" description="Create an empty timeline, then preview and add the takes you want. Nothing is added or rendered automatically." /> : versions.isLoading ? <LoadingState label="Loading timeline versions…" /> : versions.isError ? <button className="secondary-button" type="button" onClick={() => void versions.refetch()}>Retry timeline versions</button> : <TimelineEditor key={timeline.id} assets={assets.filter((asset) => asset.project_id === projectId)} initialTracks={normalizeTracks(latest)} latest={latest} timelineId={timeline.id} board={board.data ?? []} boardError={board.isError} assistantOpen={assistantOpen} onToggleAssistant={onToggleAssistant} onAssistantHost={onAssistantHost} onComposerHost={onComposerHost} />}
    {!timeline ? <aside className="desk-assistant" aria-label="Editing assistant" hidden={!assistantOpen}><header><strong>Darius</strong><button type="button" className="icon-button" aria-label="Close editing assistant" onClick={onToggleAssistant}><X size={17} /></button></header><div className="desk-assistant-host" ref={onAssistantHost} /><div className="desk-assistant-composer" ref={onComposerHost} /></aside> : null}
  </div>;
}

function TimelineEditor({ assets, initialTracks, latest, timelineId, board, boardError, assistantOpen, onToggleAssistant, onAssistantHost, onComposerHost }: { assets: Asset[]; initialTracks: TimelineTrack[]; latest?: TimelineVersion; timelineId: string; board: ShotBoardEntry[]; boardError: boolean } & DeskOptions) {
  const projectId = useDariusStore((state) => state.activeProjectId)!;
  const project = useDariusStore((state) => state.projects.find((item) => item.id === projectId));
  const fps = project?.default_fps || 24;
  const draft = useTimelineDraft(projectId, timelineId, initialTracks, latest);
  const { tracks, commit: setTracks, base, dirty } = draft;
  const scope = `edit:${projectId}:${timelineId}`;
  const [selectedId, setSelectedId] = useWorkspaceState<string | null>(`${scope}:clip`, tracks.flatMap((track) => track.clips)[0]?.id ?? null);
  const [selectedTrack, setSelectedTrack] = useWorkspaceState(`${scope}:track`, Math.max(0, tracks.findIndex((track) => track.clips.length)));
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useWorkspaceState(`${scope}:time`, 0);
  const [sourceId, setSourceId] = useWorkspaceState<string | null>(`${scope}:source`, null);
  const [tab, setTab] = useWorkspaceState<"media" | "shots">(`${scope}:tab`, "media");
  const [kind, setKind] = useWorkspaceState(`${scope}:kind`, "all");
  const [search, setSearch] = useWorkspaceState(`${scope}:search`, "");
  const [inspectorOpen, setInspectorOpen] = useWorkspaceState(`${scope}:inspector`, true);
  const [zoom, setZoom] = useWorkspaceState(`${scope}:zoom`, 32);
  const [mobilePanel, setMobilePanel] = useState<"preview" | "media" | "inspector">("preview");
  const [snapping, setSnapping] = useState(true);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const client = useQueryClient();
  const incoming = latest && latest.version_number > (base?.version_number ?? 0);
  if (incoming && !dirty) {
    draft.adopt(initialTracks, latest); setPlaying(false);
    setSelectedId(initialTracks.flatMap((track) => track.clips)[0]?.id ?? null);
    setSelectedTrack(Math.max(0, initialTracks.findIndex((track) => track.clips.length)));
  }
  const selected = tracks[selectedTrack]?.clips.find((clip) => clip.id === selectedId);
  const selectedAsset = assets.find((asset) => asset.id === selected?.source_asset_id);
  const source = assets.find((asset) => asset.id === sourceId);
  const duration = sequenceDuration(tracks);
  if (time > duration) { setTime(duration); setPlaying(false); }
  const problem = previewIssue(tracks, assets);
  const media = assets.filter((asset) => asset.role !== "derivative" && ["image", "video", "audio"].includes(asset.kind));
  const q = search.trim().toLowerCase();
  const matches = (asset: Asset) => (kind === "all" || asset.kind === kind) && assetName(asset).toLowerCase().includes(q);
  const rowFor = (asset?: Asset, clip?: TimelineClip) => board.find((row) => row.shot.id === (clip?.shot_id ?? asset?.shot_id) || row.takes.some((take) => take.id === asset?.id));
  const clipName = (clip: TimelineClip) => {
    const asset = assets.find((item) => item.id === clip.source_asset_id), row = rowFor(asset, clip);
    return row ? `S${row.scene_number} · Shot ${row.shot.number} — ${assetName(asset)}` : asset ? assetName(asset) : clip.text ?? "Missing media";
  };
  const selection = useDariusStore((state) => state.selection);
  const selectionId = selection?.type === "asset" ? selection.id : null;
  const [followedAsset, setFollowedAsset] = useState(selectionId);
  if (selectionId !== followedAsset) {
    setFollowedAsset(selectionId);
    if (selectionId) {
      const index = tracks.findIndex((track) => track.clips.some((clip) => clip.source_asset_id === selectionId));
      const clip = tracks[index]?.clips.find((item) => item.source_asset_id === selectionId);
      if (clip) { setSelectedTrack(index); setSelectedId(clip.id); }
    }
  }
  useEffect(() => {
    if (!playing) return;
    const pause = () => { if (document.hidden) setPlaying(false); };
    document.addEventListener("visibilitychange", pause);
    return () => document.removeEventListener("visibilitychange", pause);
  }, [playing]);
  const save = useMutation({
    mutationFn: (snapshot: TimelineTrack[]) => api.createTimelineVersion(timelineId, { tracks: snapshot, state: "draft", edit_summary: `Manual trim, order, mute, and delete decisions. Based on ${base ? `v${base.version_number}` : "an empty assembly"}.` }),
    onSuccess: (saved, snapshot) => { draft.markSaved(snapshot, saved); return client.invalidateQueries({ queryKey: queryKeys.timelineVersions(timelineId) }); },
  });
  const render = useMutation({
    mutationFn: async (snapshot: TimelineTrack[]) => {
      const accepted = await api.createTimelineVersion(timelineId, { tracks: snapshot, state: "accepted", edit_summary: "Accepted in Edit and explicitly approved for FFmpeg rendering." });
      draft.markSaved(snapshot, accepted);
      return api.renderTimeline(timelineId, accepted.id, true);
    },
    onSuccess: async (job) => { useDariusStore.getState().rememberJob(job); await client.invalidateQueries({ queryKey: queryKeys.timelineVersions(timelineId) }); await client.invalidateQueries({ queryKey: ["jobs"] }); },
  });
  const exportVersion = useMutation({
    mutationFn: () => api.timelineOtio(timelineId, base!.id),
    onSuccess: (document) => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], { type: "application/vnd.pixar.opentimelineio+json" }));
      const link = window.document.createElement("a"); link.href = url; link.download = `darius-${timelineId}-v${base!.version_number}.otio.json`; link.click(); URL.revokeObjectURL(url);
    },
  });
  function selectClip(clip: TimelineClip, index: number) { setSelectedTrack(index); setSelectedId(clip.id); setTime(clip.timeline_in); setSourceId(null); }
  function updateSelected(patch: Partial<TimelineClip>) {
    setPlaying(false);
    if (Object.values(patch).some((value) => typeof value === "number" && !Number.isFinite(value))) return;
    if (!selectedId) return;
    if (patch.source_in !== undefined || patch.source_out !== undefined) {
      setTracks((current) => trimClip(current, selectedTrack, selectedId, patch, selectedAsset?.duration ?? 86400), "Trim clip");
    } else setTracks((current) => current.map((track, index) => index !== selectedTrack ? track : { ...track, clips: track.clips.map((clip) => clip.id === selectedId ? { ...clip, ...patch } : clip) }), "Adjust clip sound");
  }
  function moveSelected(direction: number) {
    const current = tracks[selectedTrack]; if (!current) return;
    const clips = [...current.clips], index = clips.findIndex((clip) => clip.id === selectedId), to = index + direction;
    if (index < 0 || to < 0 || to >= clips.length) return;
    [clips[index], clips[to]] = [clips[to], clips[index]]; setPlaying(false);
    setTracks((items) => items.map((track, i) => i === selectedTrack ? { ...track, clips: reflowClips(clips) } : track), "Reorder clip");
  }
  function addAsset(asset: Asset, shotId?: string) {
    if (!media.some((item) => item.id === asset.id)) return;
    const trackKind = asset.kind === "audio" ? "audio" : "video";
    const found = tracks.findIndex((track) => track.kind === trackKind), index = found < 0 ? tracks.length : found;
    const clips = found < 0 ? [] : tracks[found].clips;
    const start = Math.max(0, ...clips.map((clip) => clip.timeline_out));
    const length = Math.max(.001, asset.duration ?? 5);
    const clip = { id: crypto.randomUUID(), source_asset_id: asset.id, shot_id: shotId ?? asset.shot_id ?? undefined, source_in: 0, source_out: length, timeline_in: start, timeline_out: start + length };
    setTracks((items) => found < 0 ? [...items, { kind: trackKind, clips: [clip] }] : items.map((track, i) => i === index ? { ...track, clips: [...track.clips, clip] } : track), "Add take");
    setSelectedTrack(index); setSelectedId(clip.id); setPlaying(false); setSourceId(null); setTime(start);
  }
  const splitTime = Math.round(time * fps) / fps;
  const canSplit = Boolean(selected && splitTime - selected.timeline_in >= 1 / fps - .00001 && selected.timeline_out - splitTime >= 1 / fps - .00001);
  function splitSelected() {
    if (!selectedId || !canSplit) return;
    setPlaying(false); setTracks((current) => splitClip(current, selectedTrack, selectedId, splitTime, crypto.randomUUID()), "Split clip");
  }
  function deleteSelected(ripple: boolean) {
    if (!selectedId) return;
    setPlaying(false); setTracks((current) => removeClip(current, selectedTrack, selectedId, ripple), ripple ? "Ripple delete" : "Delete leaving gap");
  }
  function historyStep(redo: boolean) { setPlaying(false); if (redo) draft.redo(); else draft.undo(); }
  // Only focused editor controls receive shortcuts. Chat/fields keep native behavior.
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.defaultPrevented || event.isComposing || !target?.closest(".director-desk") || target.closest("input, textarea, select, [contenteditable], .desk-assistant, .desk-library")) return;
      const action = editShortcut(event); if (!action) return;
      // Space on a focused button must click that button, not also toggle playback.
      if (event.key === " " && target.closest("button, summary")) return;
      event.preventDefault();
      const step = (event.shiftKey ? 10 : 1) / fps;
      if (action === "play") { if (duration && !problem) { setSourceId(null); if (!playing && time >= duration - .001) setTime(0); setPlaying(!playing); } return; }
      if (action === "undo" || action === "redo") { historyStep(action === "redo"); return; }
      if (action === "save") { if (!save.isPending && !render.isPending) save.mutate(tracks); return; }
      if (action === "help") { setShortcutsOpen(!shortcutsOpen); return; }
      if (action === "cancel") { setShortcutsOpen(false); return; }
      if (action === "snap") { setSnapping(!snapping); return; }
      setPlaying(false); setSourceId(null);
      if (action === "previous-frame" || action === "next-frame") { setTime(Math.max(0, Math.min(duration, (Math.round(time * fps) + (action === "next-frame" ? 1 : -1) * (event.shiftKey ? 10 : 1)) / fps))); return; }
      if (action === "home" || action === "end") { setTime(action === "home" ? 0 : duration); return; }
      if (action === "split") { splitSelected(); return; }
      if (action === "delete" || action === "ripple-delete") { deleteSelected(action === "ripple-delete"); return; }
      if (!selected || !selectedId) return;
      if (action === "mute") { updateSelected({ muted: !selected.muted }); return; }
      if (action === "trim-start" && canSplit) { updateSelected({ source_in: (selected.source_in ?? 0) + splitTime - selected.timeline_in }); return; }
      if (action === "trim-end" && canSplit) { updateSelected({ source_out: (selected.source_in ?? 0) + splitTime - selected.timeline_in }); return; }
      if (action === "move-left" || action === "move-right") { setTracks((current) => moveClipTo(current, selectedTrack, selectedId, Math.max(0, selected.timeline_in + (action === "move-right" ? step : -step))), "Nudge clip"); return; }
      if (["in-left", "in-right", "out-left", "out-right"].includes(action)) {
        const edge = action.startsWith("in-") ? "in" : "out", direction = action.endsWith("right") ? 1 : -1;
        setTracks((current) => dragTrim(current, selectedTrack, selectedId, edge, (edge === "in" ? selected.timeline_in : selected.timeline_out) + direction / fps, selectedAsset?.duration ?? 86400, fps), "Nudge trim");
      }
    };
    window.addEventListener("keydown", keyboard); return () => window.removeEventListener("keydown", keyboard);
  });
  function mediaCard(asset: Asset, shot?: ShotBoardEntry) {
    return <article className="desk-media-card" key={asset.id} draggable onDragStart={(event) => event.dataTransfer.setData("application/x-darius-asset", asset.id)}>
      <button className="desk-media-preview" type="button" aria-label={`Preview ${assetName(asset)}`} onClick={() => { setPlaying(false); setSourceId(asset.id); }}><EditThumbnail asset={asset} assets={assets} /><span className="desk-media-duration">{asset.kind} · {editClock(asset.duration ?? 5)}</span></button>
      <div><strong title={assetName(asset)}>{assetName(asset)}</strong>{shot?.shot.selected_asset_id === asset.id ? <small className="desk-chosen"><Check size={11} />Chosen take</small> : <small>{shot ? `Shot ${shot.shot.number} take` : asset.provider || "Project media"}</small>}<button className="desk-add" type="button" aria-label={`Add ${assetName(asset)} to timeline`} onClick={() => addAsset(asset, shot?.shot.id)}><Plus size={13} />Add</button></div>
    </article>;
  }
  const error = save.error || render.error || exportVersion.error;
  return <>
    {draft.storageError ? <p className="form-error" role="alert">{draft.storageError}</p> : null}
    {draft.recovered ? <p className="project-sync-notice" role="status">Recovered your browser-local cut. Save a new version to sync it to your other devices.</p> : null}
    {draft.candidates.length ? <div className="desk-recovery" role="status"><strong>Browser draft recovery</strong><small>These unsaved cuts belong to this project and timeline, possibly another open tab. Restoring never merges or overwrites a saved version.</small>{draft.candidates.map((record) => <div key={record.key}><span>{new Date(record.cut.updatedAt).toLocaleString()} · {record.cut.base ? `based on v${record.cut.base.version_number}` : "empty assembly"}</span><button type="button" className="secondary-button" onClick={() => { if (!dirty || window.confirm("Replace the open unsaved cut with this browser recovery? Save your current cut as a version first if you want to keep both.")) { draft.restore(record); setPlaying(false); setTime(0); setSelectedId(record.cut.tracks.flatMap((track) => track.clips)[0]?.id ?? null); setSelectedTrack(Math.max(0, record.cut.tracks.findIndex((track) => track.clips.length))); } }}>Restore local draft</button><button type="button" className="text-button" onClick={() => { if (window.confirm("Delete this browser recovery? This cannot be undone and could belong to another open tab. Saved timeline versions are not affected.")) draft.discard(record); }}>Discard recovery</button></div>)}</div> : null}
    <nav className="desk-mobile-panels" aria-label="Editing panels">{(["preview", "media", "inspector"] as const).map(panel => <button className="secondary-button" key={panel} aria-pressed={mobilePanel === panel} type="button" onClick={() => { setMobilePanel(panel); if (panel === "inspector") setInspectorOpen(true); }}>{panel === "preview" ? "Preview" : panel === "media" ? "Media bin" : "Clip details"}</button>)}</nav>
    <div className={`desk-workspace show-${mobilePanel} ${inspectorOpen ? "has-clip-inspector" : ""} ${assistantOpen ? "has-assistant" : ""}`}>
      <aside className="desk-library" aria-label="Shot and take browser">
        <div className="desk-panel-title"><FolderOpen size={15} /><strong>Your material</strong><span>{media.length}</span></div>
        <div className="desk-tabs" role="group" aria-label="Library view"><button type="button" aria-pressed={tab === "media"} onClick={() => setTab("media")}>Project media</button><button type="button" aria-pressed={tab === "shots"} onClick={() => setTab("shots")}>Shots & takes</button></div>
        <label className="desk-search"><Search size={14} /><input aria-label="Search editing media" placeholder="Find a take…" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        <div className="desk-kind-filters" role="group" aria-label="Media type">{["all", "video", "image", "audio"].map((item) => <button type="button" key={item} aria-pressed={kind === item} onClick={() => setKind(item)}>{item}</button>)}</div>
        <div className="desk-library-scroll">{tab === "media" ? <><div className="desk-media-grid">{media.filter(matches).map((asset) => mediaCard(asset, rowFor(asset)))}</div>{!media.filter(matches).length ? <p className="desk-empty">No matching project media. Generate or import assets in Create.</p> : null}</> : <>
          {boardError ? <p className="form-error">Could not load shots. Project media remains available.</p> : null}
          {board.filter((row) => !q || `${row.scene_title} ${row.shot.description}`.toLowerCase().includes(q) || row.takes.some(matches)).map((row) => <section className="desk-shot-group" key={row.shot.id}><span className="eyebrow">Scene {row.scene_number} · {row.scene_title}</span><h3>Shot {row.shot.number}</h3><p>{row.shot.description || "No description yet"}</p><div className="desk-media-grid">{row.takes.filter((asset) => media.some((item) => item.id === asset.id) && (kind === "all" || asset.kind === kind)).map((asset) => mediaCard(asset, row))}</div>{!row.takes.length ? <small>No takes yet</small> : null}</section>)}
          {!board.length && !boardError ? <p className="desk-empty">No shots yet. Your generated and imported assets are in Project media.</p> : null}
        </>}</div><small className="desk-library-hint">Preview a take, then Add or drag it onto the timeline.</small>
      </aside>
      <div className="desk-stage">
        <div className="desk-stage-tools"><div className="desk-tabs"><button type="button" aria-pressed={!source} onClick={() => { setSourceId(null); }}>Sequence</button>{source ? <button type="button" aria-pressed>Source preview</button> : null}</div><button className="icon-button" type="button" aria-label="Toggle clip inspector" aria-pressed={inspectorOpen} onClick={() => setInspectorOpen(!inspectorOpen)}>{inspectorOpen ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}</button></div>
        {source ? <section className="desk-source" aria-label="Source preview"><div className="desk-player-heading"><strong>{assetName(source)}</strong><button className="icon-button" type="button" aria-label="Close source preview" onClick={() => setSourceId(null)}><X size={17} /></button></div><div className="desk-screen"><MediaPreview asset={source} /></div><button className="secondary-button" type="button" onClick={() => addAsset(source)}><Plus size={15} />Add this take</button></section> : <SequencePlayer tracks={tracks} assets={assets} time={time} playing={playing} onTime={setTime} onPlaying={setPlaying} issue={problem} />}
      </div>
      {inspectorOpen ? <aside className="desk-clip-inspector" aria-label="Selected clip controls"><span className="eyebrow">Selected clip</span><h2>{selected ? clipName(selected) : "Choose a clip"}</h2><p>{selected ? `${editClock(selected.timeline_in)} → ${editClock(selected.timeline_out)}` : "Select a clip on the timeline to make a trim or change the order."}</p>{selected ? <><div className="clip-fields"><label>Trim in (s)<input disabled={!selected} min={0} type="number" step={1 / fps} value={selected?.source_in ?? 0} onChange={(event) => updateSelected({ source_in: Number(event.target.value) })} /></label><label>Trim out (s)<input disabled={!selected} min={.001} max={selectedAsset?.duration ?? undefined} type="number" step={1 / fps} value={selected?.source_out ?? 0} onChange={(event) => updateSelected({ source_out: Number(event.target.value) })} /></label></div><fieldset className="desk-sound-controls" disabled={!selected || !selectedAsset || !["audio", "video"].includes(selectedAsset.kind)}><legend>Clip sound · linked to picture</legend><label>Volume (%)<input type="number" min={0} max={100} step={5} value={Math.round((selected?.volume ?? 1) * 100)} onChange={(event) => updateSelected({ volume: Math.max(0, Math.min(1, Number(event.target.value) / 100)) })} /></label><label>Fade in (s)<input type="number" min={0} max={86400} step={1 / fps} value={selected?.fade_in ?? 0} onChange={(event) => updateSelected({ fade_in: Math.max(0, Math.min(86400, Number(event.target.value))), audio_start: undefined, audio_end: undefined })} /></label><label>Fade out (s)<input type="number" min={0} max={86400} step={1 / fps} value={selected?.fade_out ?? 0} onChange={(event) => updateSelected({ fade_out: Math.max(0, Math.min(86400, Number(event.target.value))), audio_start: undefined, audio_end: undefined })} /></label></fieldset><div className="desk-clip-actions"><button className="secondary-button" type="button" disabled={!selected} onClick={() => moveSelected(-1)}><ArrowUp size={14} />Earlier</button><button className="secondary-button" type="button" disabled={!selected} onClick={() => moveSelected(1)}><ArrowDown size={14} />Later</button><button className="secondary-button" type="button" disabled={!selected} onClick={() => updateSelected({ muted: !selected?.muted })}>{selected?.muted ? <Volume2 size={14} /> : <VolumeX size={14} />}{selected?.muted ? "Unmute" : "Mute"}</button><button className="text-button danger-button" type="button" disabled={!selected} onClick={() => deleteSelected(true)}><Trash2 size={14} />Ripple delete</button><button className="secondary-button" type="button" disabled={!selected} onClick={() => deleteSelected(false)}>Delete leaving gap</button><button className="secondary-button" type="button" disabled={!canSplit} onClick={splitSelected}><Scissors size={14} />Split at playhead</button></div><p className="desk-inspector-note">Trim and ripple-delete shift later clips on this track only; other tracks keep their timing. Browser recovery stays on this device. Save a version to sync. Original assets are never changed.</p></> : null}</aside> : null}
      <aside className="desk-assistant" aria-label="Editing assistant" hidden={!assistantOpen}><header><div><MessageSquare size={15} /><strong>Darius</strong></div><button className="icon-button" aria-label="Close editing assistant" type="button" onClick={onToggleAssistant}><X size={17} /></button></header><small>Project chat & voice · edit-tool commands come in a later step.</small><div className="desk-assistant-host" ref={onAssistantHost} /><div className="desk-assistant-composer" ref={onComposerHost} /></aside>
    </div>
    <div className="desk-edit-tools" role="group" aria-label="Timeline editing tools">
      <button type="button" className="secondary-button" disabled={!draft.canUndo} title={`Undo ${draft.undoLabel} (Ctrl/⌘ Z)`} onClick={() => historyStep(false)}><Undo2 size={14} />Undo</button>
      <button type="button" className="secondary-button" disabled={!draft.canRedo} title={`Redo ${draft.redoLabel ?? "edit"} (Ctrl/⌘ Shift Z)`} onClick={() => historyStep(true)}><Redo2 size={14} />Redo</button>
      <button type="button" className="secondary-button" disabled={!canSplit} onClick={splitSelected}><Scissors size={14} />Split selected clip</button>
      <label>Playhead (s)<input aria-label="Edit playhead seconds" type="number" min={0} max={duration} step={1 / fps} value={Number(time.toFixed(4))} onChange={(event) => { const value = Number(event.target.value); if (Number.isFinite(value)) { setPlaying(false); setSourceId(null); setTime(Math.max(0, Math.min(duration, Math.round(value * fps) / fps))); } }} /></label>
      <button type="button" className="secondary-button" aria-label="Previous frame" disabled={time <= 0} onClick={() => { setPlaying(false); setSourceId(null); setTime(Math.max(0, (Math.round(time * fps) - 1) / fps)); }}>−1 frame</button>
      <button type="button" className="secondary-button" aria-label="Next frame" disabled={time >= duration} onClick={() => { setPlaying(false); setSourceId(null); setTime(Math.min(duration, (Math.round(time * fps) + 1) / fps)); }}>+1 frame</button>
      <button type="button" className="secondary-button" disabled={!canSplit} onClick={() => selected && updateSelected({ source_in: (selected.source_in ?? 0) + splitTime - selected.timeline_in })}>Trim start here</button>
      <button type="button" className="secondary-button" disabled={!canSplit} onClick={() => selected && updateSelected({ source_out: (selected.source_in ?? 0) + splitTime - selected.timeline_in })}>Trim end here</button>
      <label>Zoom<input aria-label="Timeline zoom" type="range" min={12} max={160} step={4} value={zoom} onChange={(event) => setZoom(Number(event.target.value))} /></label>
      <button type="button" className="secondary-button" aria-expanded={shortcutsOpen} onClick={() => setShortcutsOpen(!shortcutsOpen)}>Keyboard shortcuts · ?</button>
    </div>
    {shortcutsOpen ? <div className="desk-shortcuts" role="region" aria-label="Editing keyboard shortcuts"><strong>Focus the timeline to edit. Chat and inputs keep their usual keys.</strong><dl><dt>Space / K</dt><dd>Play / pause (Space clicks a focused button)</dd><dt>← / → · Shift for 10</dt><dd>Step frames</dd><dt>S</dt><dd>Split selected clip at playhead</dd><dt>Q / W</dt><dd>Ripple trim start / end to playhead</dd><dt>[ / ]</dt><dd>Trim start − / + one frame; Shift trims end</dd><dt>Alt + ← / →</dt><dd>Move clip one frame; Shift for 10, no overlaps</dd><dt>Delete · Shift+Delete</dt><dd>Delete leaving gap · ripple delete</dd><dt>M · N</dt><dd>Mute clip · toggle snapping</dd><dt>Home / End</dt><dd>Sequence start / end</dd><dt>Ctrl/⌘ S · Z · Shift+Z</dt><dd>Save version · undo · redo (never render)</dd><dt>Esc · ?</dt><dd>Cancel drag / close help · toggle help</dd></dl></div> : null}
    <section className="desk-timeline" aria-label="Project timeline" tabIndex={0} onDragOver={(event) => { if (event.dataTransfer.types.includes("application/x-darius-asset")) event.preventDefault(); }} onDrop={(event) => { event.preventDefault(); const asset = media.find((item) => item.id === event.dataTransfer.getData("application/x-darius-asset")); if (asset) addAsset(asset); }}>
      <header className="desk-timeline-heading"><div><Film size={15} /><strong>{base ? `Timeline v${base.version_number} · ${base.state}` : "New assembly"}</strong><span className={dirty ? "desk-dirty" : ""}>{dirty ? "Unsaved changes" : base ? "Saved" : "Empty"}</span></div><span>{duration.toFixed(1)} seconds · {tracks.flatMap((track) => track.clips).length} clips</span></header>
      {incoming && dirty ? <div className="project-sync-notice" role="status">A newer timeline version is available. Your unsaved cut is safe. Save it as a separate new version, or <button className="text-button" type="button" onClick={() => { if (window.confirm("Discard your unsaved cut and load the latest saved version?")) { draft.adopt(initialTracks, latest); setPlaying(false); setTime(0); } }}>load the latest version</button>.</div> : null}
      <TimelineStrip tracks={tracks} assets={assets} time={time} fps={fps} zoom={zoom} selectedId={selectedId} selectedTrack={selectedTrack} snapping={snapping} onSnapping={setSnapping} clipName={clipName} onSelect={selectClip} onSeek={(value) => { setPlaying(false); setSourceId(null); setTime(value); }} onCommit={setTracks} onInteraction={() => { setPlaying(false); setSourceId(null); }} />
      {!duration ? <p className="desk-empty"><Scissors size={16} />Add or drop a take here to begin.</p> : null}
    </section>
    {error ? <p className="form-error" role="alert">{error instanceof ApiError ? error.message : error instanceof Error ? error.message : "This timeline action could not be completed."}</p> : null}
    <footer className="desk-footer"><div><button className="primary-button" type="button" disabled={save.isPending || render.isPending} onClick={() => save.mutate(tracks)}>{save.isPending ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}Save new version</button><button className="secondary-button" type="button" disabled={!pictureClips(tracks).length || Boolean(problem) || render.isPending || save.isPending} onClick={() => { setPlaying(false); render.mutate(tracks); }}><Film size={15} />Approve &amp; render</button><button className="text-button" type="button" title="Exports the last saved version, not unsaved changes" disabled={!base || exportVersion.isPending} onClick={() => exportVersion.mutate()}><Download size={15} />Export OTIO</button></div><div>{render.data ? <RenderJobStatus key={render.data.id} jobId={render.data.id} projectId={projectId} initialJob={render.data} /> : <span>Save freely. Rendering always requires your approval.</span>}</div></footer>
  </>;
}
