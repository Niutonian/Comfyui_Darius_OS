"use client";
import { RenderJobStatus } from "./render-job-status";
/* eslint-disable @next/next/no-img-element -- bin thumbnails are local API files */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Download, LoaderCircle, Maximize2, Pause, Play, Save, Scissors, SkipBack, SkipForward, Sparkles, Trash2, Volume2, VolumeX } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api-client";
import { queryKeys, useTimelines, useTimelineVersions } from "@/lib/queries";
import { useDariusStore } from "@/lib/store";
import type { Asset, TimelineClip, TimelineTrack, TimelineVersion } from "@/lib/types";
import { MediaPreview } from "./media-preview";
import { EmptyState, LoadingState } from "./states";

function seededTracks(assets: Asset[]): TimelineTrack[] {
  let pictureCursor = 0;
  let audioCursor = 0;
  const picture = assets.filter((asset) => asset.kind === "video" || asset.kind === "image").map((asset) => {
    const duration = asset.duration ?? 5;
    const clip = { id: `asset-${asset.id}`, source_asset_id: asset.id, source_in: 0, source_out: duration, timeline_in: pictureCursor, timeline_out: pictureCursor + duration };
    pictureCursor += duration;
    return clip;
  });
  const audio = assets.filter((asset) => asset.kind === "audio").map((asset) => {
    const duration = asset.duration ?? 5;
    const clip = { id: `asset-${asset.id}`, source_asset_id: asset.id, source_in: 0, source_out: duration, timeline_in: audioCursor, timeline_out: audioCursor + duration };
    audioCursor += duration;
    return clip;
  });
  return [{ kind: "video", clips: picture }, { kind: "audio", clips: audio }];
}

function normalizeTracks(version: TimelineVersion | undefined, assets: Asset[]): TimelineTrack[] {
  if (!version) return seededTracks(assets);
  return version.tracks.map((track, trackIndex) => {
    const value = track as { kind?: string; clips?: Array<Record<string, unknown>> };
    return {
      kind: value.kind ?? `track-${trackIndex + 1}`,
      clips: (value.clips ?? []).map((clip, clipIndex) => ({
        ...clip,
        id: String(clip.id ?? `clip-${trackIndex}-${clipIndex}`),
        timeline_in: Number(clip.timeline_in ?? 0),
        timeline_out: Number(clip.timeline_out ?? 0),
      })) as TimelineClip[],
    };
  });
}

// Keep the previous bench available while the new desk is introduced.
export { DirectorDesk as EditView } from "./director-desk";

export function LegacyEditView({ assets }: { assets: Asset[] }) {
  const activeProjectId = useDariusStore((state) => state.activeProjectId);
  const [chosenTimelineId, setChosenTimelineId] = useState("");
  const timelines = useTimelines(activeProjectId);
  const selectedTimeline = timelines.data?.find((item) => item.id === chosenTimelineId) ?? timelines.data?.[0];
  if (!chosenTimelineId && selectedTimeline) setChosenTimelineId(selectedTimeline.id);
  const versions = useTimelineVersions(selectedTimeline?.id ?? null);
  const latest = useMemo(() => [...(versions.data ?? [])].sort((a, b) => b.version_number - a.version_number)[0], [versions.data]);
  const client = useQueryClient();
  const createMutation = useMutation({
    mutationFn: () => api.createTimeline({ project_id: activeProjectId!, name: "Project assembly" }),
    onSuccess: (timeline) => { setChosenTimelineId(timeline.id); void client.invalidateQueries({ queryKey: queryKeys.timelines(activeProjectId!) }); },
  });
  const proposeMutation = useMutation({
    mutationFn: () => api.proposeTimeline(selectedTimeline!.id, selectedTimeline!.scene_id),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.timelineVersions(selectedTimeline!.id) }),
  });

  if (!activeProjectId) return <div className="view edit-view"><header className="view-heading"><div><span className="eyebrow">Focused cut</span><h1>Edit</h1><p>Shape a clear sequence without the complexity of a full NLE.</p></div></header><EmptyState title="Choose a project to edit" description="The focused timeline is scoped to one durable project." /></div>;
  if (timelines.isLoading) return <div className="view edit-view"><LoadingState label="Loading persisted timelines…" /></div>;

  return <div className="view edit-view">
    <header className="view-heading"><div><span className="eyebrow">Focused cut</span><h1>Edit</h1><p>Persist simple editorial decisions as immutable timeline versions.</p></div><div className="edit-header-actions">{selectedTimeline ? <button className="primary-button" disabled={proposeMutation.isPending} onClick={() => proposeMutation.mutate()} type="button">{proposeMutation.isPending ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />} Propose from shots</button> : <button className="primary-button" disabled={createMutation.isPending} onClick={() => createMutation.mutate()} type="button">{createMutation.isPending ? <LoaderCircle className="spin" size={16} /> : <Scissors size={16} />} Create timeline</button>}</div></header>
    {timelines.error || createMutation.error || proposeMutation.error ? <p className="form-error edit-notice" role="alert">{[timelines.error, createMutation.error, proposeMutation.error].find(Boolean) instanceof ApiError ? ([timelines.error, createMutation.error, proposeMutation.error].find(Boolean) as ApiError).message : "The timeline could not be updated."}</p> : null}
    {!selectedTimeline ? <EmptyState title="Start the first cut" description="Create a persisted timeline, then add assets or propose an assembly from selected shots." /> : <>
      <div className="timeline-select-row"><label>Timeline<select onChange={(event) => setChosenTimelineId(event.target.value)} value={selectedTimeline.id}>{timelines.data?.map((timeline) => <option key={timeline.id} value={timeline.id}>{timeline.name}</option>)}</select></label><span>{versions.data?.length ?? 0} persisted {versions.data?.length === 1 ? "version" : "versions"}</span></div>
      {versions.isLoading ? <LoadingState label="Loading timeline versions…" /> : <TimelineEditor assets={assets} initialTracks={normalizeTracks(latest, assets)} key={selectedTimeline.id} latest={latest} timelineId={selectedTimeline.id} />}
    </>}
  </div>;
}

function formatClock(seconds: number) {
  const whole = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}

function TimelineEditor({ assets, initialTracks, latest, timelineId }: { assets: Asset[]; initialTracks: TimelineTrack[]; latest?: TimelineVersion; timelineId: string }) {
  const activeProjectId = useDariusStore((state) => state.activeProjectId);
  const [tracks, setTracks] = useState(initialTracks);
  const [baseVersion, setBaseVersion] = useState(latest);
  const [baseline, setBaseline] = useState(() => JSON.stringify(initialTracks));
  const dirty = JSON.stringify(tracks) !== baseline;
  const incoming = latest && latest.version_number > (baseVersion?.version_number ?? 0);
  const [selectedId, setSelectedId] = useState<string | null>(initialTracks.flatMap((track) => track.clips)[0]?.id ?? null);
  // Remote versions can advance a clean editor, but must never remount an unsaved cut.
  if (incoming && !dirty) {
    setTracks(initialTracks); setBaseline(JSON.stringify(initialTracks)); setBaseVersion(latest);
    setSelectedId(initialTracks.flatMap((track) => track.clips)[0]?.id ?? null);
  }
  const [playing, setPlaying] = useState(false);
  const [binKind, setBinKind] = useState("all");
  const [playhead, setPlayhead] = useState(0);
  const selection = useDariusStore((state) => state.selection);
  const client = useQueryClient();
  const clips = tracks.flatMap((track) => track.clips);
  const selected = clips.find((clip) => clip.id === selectedId);
  const selectedAsset = assets.find((asset) => asset.id === selected?.source_asset_id);
  const duration = Math.max(0, ...clips.map((clip) => clip.timeline_out));
  const binAssets = assets.filter((asset) => asset.role !== "derivative" && (binKind === "all" || asset.kind === binKind));
  const selectionAssetId = selection?.type === "asset" ? selection.id : null;
  const [followedAssetId, setFollowedAssetId] = useState(selectionAssetId);
  if (selectionAssetId !== followedAssetId) {
    setFollowedAssetId(selectionAssetId);
    const clip = tracks.flatMap((track) => track.clips).find((item) => item.source_asset_id === selectionAssetId);
    if (clip) setSelectedId(clip.id);
  }
  useEffect(() => {
    if (!playing || duration <= 0) return;
    const timer = window.setInterval(() => setPlayhead((value) => (value + 0.1) % duration), 100);
    return () => window.clearInterval(timer);
  }, [duration, playing]);
  const saveMutation = useMutation({
    mutationFn: (snapshot: TimelineTrack[]) => api.createTimelineVersion(timelineId, { tracks: snapshot, state: "draft", edit_summary: `Manual trim, order, mute, and delete decisions. Based on ${baseVersion ? `v${baseVersion.version_number}` : "an unsaved assembly"}.` }),
    onSuccess: (saved, snapshot) => {
      setBaseline(JSON.stringify(snapshot)); setBaseVersion(saved);
      return client.invalidateQueries({ queryKey: queryKeys.timelineVersions(timelineId) });
    },
  });
  const renderMutation = useMutation({
    mutationFn: async () => {
      const accepted = await api.createTimelineVersion(timelineId, {
        tracks,
        state: "accepted",
        edit_summary: "Accepted in Edit and explicitly approved for FFmpeg rendering.",
      });
      setBaseline(JSON.stringify(tracks)); setBaseVersion(accepted);
      return api.renderTimeline(timelineId, accepted.id, true);
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: queryKeys.timelineVersions(timelineId) });
      await client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const exportMutation = useMutation({
    mutationFn: () => api.timelineOtio(timelineId, baseVersion!.id),
    onSuccess: (document) => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], { type: "application/vnd.pixar.opentimelineio+json" }));
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = `darius-${timelineId}-v${baseVersion!.version_number}.otio.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });

  function replaceTrack(trackIndex: number, nextClips: TimelineClip[]) {
    let cursor = 0;
    const timed = nextClips.map((clip) => {
      const clipDuration = Math.max(0.001, (clip.source_out ?? clip.timeline_out) - (clip.source_in ?? clip.timeline_in));
      const next = { ...clip, timeline_in: cursor, timeline_out: cursor + clipDuration };
      cursor += clipDuration;
      return next;
    });
    setTracks((current) => current.map((track, index) => index === trackIndex ? { ...track, clips: timed } : track));
  }

  function updateSelected(patch: Partial<TimelineClip>) {
    setTracks((current) => current.map((track) => {
      let cursor = 0;
      const clips = track.clips.map((clip) => clip.id === selectedId ? { ...clip, ...patch } : clip).map((clip) => {
        const clipDuration = Math.max(0.001, (clip.source_out ?? clip.timeline_out) - (clip.source_in ?? clip.timeline_in));
        const timed = { ...clip, timeline_in: cursor, timeline_out: cursor + clipDuration };
        cursor += clipDuration;
        return timed;
      });
      return { ...track, clips };
    }));
  }

  function moveSelected(direction: -1 | 1) {
    const trackIndex = tracks.findIndex((track) => track.clips.some((clip) => clip.id === selectedId));
    if (trackIndex < 0) return;
    const next = [...tracks[trackIndex].clips];
    const index = next.findIndex((clip) => clip.id === selectedId);
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    replaceTrack(trackIndex, next);
  }

  function addAsset(asset: Asset) {
    const kind = asset.kind === "audio" ? "audio" : "video";
    const trackIndex = Math.max(0, tracks.findIndex((track) => track.kind === kind));
    const existing = tracks[trackIndex]?.clips.find((clip) => clip.source_asset_id === asset.id);
    if (existing) { setSelectedId(existing.id); return; }
    const length = asset.duration ?? 5;
    const clip = { id: `asset-${asset.id}`, source_asset_id: asset.id, source_in: 0, source_out: length, timeline_in: 0, timeline_out: length };
    replaceTrack(trackIndex, [...(tracks[trackIndex]?.clips ?? []), clip]);
    setSelectedId(clip.id);
  }
  function deleteSelected() {
    const trackIndex = tracks.findIndex((track) => track.clips.some((clip) => clip.id === selectedId));
    if (trackIndex < 0) return;
    replaceTrack(trackIndex, tracks[trackIndex].clips.filter((clip) => clip.id !== selectedId));
    setSelectedId(null);
  }

  const ratio = duration > 0 ? Math.min(1, playhead / duration) : 0;
  return <div className="edit-bench">
    <aside className="edit-bin" aria-label="Asset bin">
      <strong>Assets</strong>
      <div className="edit-bin-filters">{(["all", "image", "video", "audio"] as const).map((kind) => <button aria-pressed={binKind === kind} key={kind} onClick={() => setBinKind(kind)} type="button">{kind === "all" ? "All" : kind[0].toUpperCase() + kind.slice(1)}</button>)}</div>
      {binAssets.map((asset) => <button className={`edit-bin-item ${selectedAsset?.id === asset.id ? "selected" : ""}`} key={asset.id} onClick={() => addAsset(asset)} type="button"><span className="edit-bin-thumb">{asset.kind === "audio" ? <span>♪</span> : <img alt="" src={api.assetContentUrl(asset.id)} />}</span><span><strong>{asset.metadata.display_name ? String(asset.metadata.display_name) : asset.id.slice(0, 8)}</strong><small>{asset.kind}{asset.duration ? ` · ${formatClock(asset.duration)}` : ""}</small></span></button>)}
      {!binAssets.length ? <p className="map-search-empty">No media in this project yet.</p> : null}
    </aside>
    <div className="edit-stage">
    {incoming && dirty ? <div className="project-sync-notice" role="status">A newer timeline version is available. Your unsaved cut is safe. Save it as a separate new version, or <button className="text-button" type="button" onClick={() => { if (window.confirm("Discard your unsaved cut and load the latest saved version?")) { setTracks(initialTracks); setBaseline(JSON.stringify(initialTracks)); setBaseVersion(latest); setPlaying(false); } }}>load the latest version</button>.</div> : null}
    <section aria-label="Preview player" className="player-panel"><div className="player-screen">{selectedAsset ? <MediaPreview asset={selectedAsset} /> : <div className="player-empty"><Play size={34} /><span>Select a media clip to inspect it.</span></div>}</div><div className="transport"><span className="timecode">{formatClock(playhead)} / {formatClock(duration)}</span><div><button aria-label="Previous clip" className="icon-button" onClick={() => moveSelected(-1)} type="button"><SkipBack size={17} /></button><button aria-label={playing ? "Pause" : "Play"} className="play-button" onClick={() => setPlaying((value) => !value)} type="button">{playing ? <Pause size={18} /> : <Play size={18} />}</button><button aria-label="Next clip" className="icon-button" onClick={() => moveSelected(1)} type="button"><SkipForward size={17} /></button></div><div><button aria-label="Toggle selected clip mute" className="icon-button" disabled={!selected} onClick={() => updateSelected({ muted: !selected?.muted })} type="button">{selected?.muted ? <VolumeX size={17} /> : <Volume2 size={17} />}</button><button aria-label="Fullscreen" className="icon-button" type="button"><Maximize2 size={17} /></button></div></div></section>
    <section aria-label="Project timeline" className="timeline-panel" style={{ ["--playhead" as string]: `${12 + ratio * 76}%` }}><div className="timeline-toolbar"><span><Scissors size={14} /> {baseVersion ? `Timeline v${baseVersion.version_number} · ${baseVersion.state}${dirty ? " · unsaved changes" : ""}` : "Unsaved assembly"}</span><span>{duration.toFixed(1)} seconds</span></div><div className="ruler">{[0, .2, .4, .6, .8, 1].map((step) => <span key={step}>{(duration * step).toFixed(0)}s</span>)}</div>{tracks.map((track, trackIndex) => <div className="track" key={`${track.kind}-${trackIndex}`}><span className="track-label"><strong>{track.kind === "video" ? "V" : "A"}{trackIndex + 1}</strong><small>{track.kind}</small></span><div className="track-lane">{track.clips.map((clip, index) => <button aria-pressed={selectedId === clip.id} className={`timeline-clip ${track.kind === "video" ? "video-clip" : "audio-clip"} ${clip.muted ? "muted-clip" : ""} ${selectedId === clip.id ? "selected" : ""}`} key={clip.id} onClick={() => setSelectedId(clip.id)} style={{ flex: Math.max(.25, clip.timeline_out - clip.timeline_in) }} type="button"><i>{String(index + 1).padStart(2, "0")}</i><span>{clip.source_asset_id?.slice(0, 6) ?? clip.text?.slice(0, 16) ?? "clip"}</span>{clip.muted ? <VolumeX size={11} /> : null}</button>)}</div></div>)}<div className="playhead" />{!clips.length ? <p className="timeline-empty">No clips in this version. Generate/import media or propose from selected shots.</p> : null}</section>
    <section aria-label="Selected clip controls" className="clip-editor"><div><span className="eyebrow">Selected clip</span><h2>{selected ? selected.source_asset_id?.slice(0, 12) ?? selected.text ?? selected.id : "Choose a clip"}</h2></div><div className="clip-fields"><label>Trim in (s)<input disabled={!selected} min={0} onChange={(event) => updateSelected({ source_in: Number(event.target.value) })} step={0.1} type="number" value={selected?.source_in ?? 0} /></label><label>Trim out (s)<input disabled={!selected} min={(selected?.source_in ?? 0) + .001} onChange={(event) => updateSelected({ source_out: Number(event.target.value) })} step={0.1} type="number" value={selected?.source_out ?? 0} /></label></div><div className="clip-actions"><button className="secondary-button" disabled={!selected} onClick={() => moveSelected(-1)} type="button"><ArrowUp size={14} /> Earlier</button><button className="secondary-button" disabled={!selected} onClick={() => moveSelected(1)} type="button"><ArrowDown size={14} /> Later</button><button className="secondary-button" disabled={!selected} onClick={() => updateSelected({ muted: !selected?.muted })} type="button">{selected?.muted ? <Volume2 size={14} /> : <VolumeX size={14} />} {selected?.muted ? "Unmute" : "Mute"}</button><button className="text-button danger-button" disabled={!selected} onClick={deleteSelected} type="button"><Trash2 size={14} /> Delete</button></div></section>
    {[saveMutation.error, renderMutation.error, exportMutation.error].find(Boolean) ? <p className="form-error edit-notice" role="alert">{[saveMutation.error, renderMutation.error, exportMutation.error].find(Boolean) instanceof ApiError ? ([saveMutation.error, renderMutation.error, exportMutation.error].find(Boolean) as ApiError).message : "The timeline action could not be completed."}</p> : null}<div className="timeline-actions"><button className="primary-button" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate(tracks)} type="button">{saveMutation.isPending ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />} Save new version</button><button className="secondary-button" disabled={!clips.length || renderMutation.isPending} onClick={() => renderMutation.mutate()} title="Creates an accepted version and queues an approved worker-only FFmpeg job" type="button">{renderMutation.isPending ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />} Approve &amp; render</button><button className="secondary-button" disabled={!baseVersion || exportMutation.isPending} onClick={() => exportMutation.mutate()} type="button">{exportMutation.isPending ? <LoaderCircle className="spin" size={15} /> : <Download size={15} />} Export OTIO</button><div>{renderMutation.data ? <RenderJobStatus key={renderMutation.data.id} jobId={renderMutation.data.id} projectId={activeProjectId} initialJob={renderMutation.data} /> : <span>Rendering requires explicit approval. Progress appears in Background jobs.</span>}</div></div>
    </div>
  </div>;
}
