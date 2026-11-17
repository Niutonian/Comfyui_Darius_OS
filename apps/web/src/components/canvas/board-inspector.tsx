"use client";
/* eslint-disable @next/next/no-img-element -- immutable local asset versions */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Copy, Layers3, Maximize, Sparkles } from "lucide-react";
import { api } from "@/lib/api-client";
import { canvasApi } from "@/lib/canvas-api";
import { canvasProfiles } from "@/lib/canvas-profile";
import { mossApi, prepareBoard, type BoardSettings, type MossBoard, type Placement, type VisualReference } from "@/lib/moss-workspace";
import type { Asset } from "@/lib/types";
import { CanvasGenerationDetails, CanvasProfileControls } from "../canvas-profile-controls";
import { ImageRecipeControls, isImageRecipeBoard } from "../image-recipe-board";
import { VideoBoardControls, isVideoBoard } from "../video-board";
import { VisualNoteThumbnail } from "./board-preview";
import { errorText } from "./use-board-layout";
import { documentPoll } from "@/lib/live-poll";

export type VideoRole = "animate-image" | "camera-direction" | "reference-video";

/** Saved document of the selected board: prompt, versions and results. Shared by inspector and history. */
export function useBoardVersions(projectId: string, board: MossBoard | undefined) {
  return useQuery({ queryKey: ["canvas", projectId, board?.documentId], queryFn: () => canvasApi.get(projectId, board!.documentId), enabled: Boolean(board), refetchInterval: documentPoll });
}

export type BoardInspectorProps = {
  projectId: string; selected: MossBoard | undefined; boards: MossBoard[]; assets: Asset[]; placement: Placement | undefined;
  creating: boolean; status: string; error: string; generateLabel: string; canGenerate: boolean; preparing: boolean;
  onSettings: (board: MossBoard, next: BoardSettings) => Promise<boolean>; onOpen: (board: MossBoard) => void; onGenerate: (board: MossBoard) => void;
  onDuplicate: (board: MossBoard) => void; onMove: (placement: Placement) => void; onFitArtwork: (board: MossBoard) => void; onJump: (board: MossBoard) => void;
  onBindVideo: (board: MossBoard, target: string, role: VideoRole) => void; onArchived: () => void;
  setError: (message: string) => void; setBoardError: (boardId: string, message: string) => void; refresh: () => void;
};

export function BoardInspector(props: BoardInspectorProps) {
  const { projectId, selected, boards, assets, placement, setError, refresh } = props;
  const [videoTarget, setVideoTarget] = useState("new"), [videoRole, setVideoRole] = useState<VideoRole>("animate-image");
  const [referenceTarget, setReferenceTarget] = useState(""), [referenceGeneration, setReferenceGeneration] = useState("");
  const versions = useBoardVersions(projectId, selected);
  const completed = versions.data?.generations.filter(g => g.status === "completed" && g.assetIds.length) ?? [];
  const chosenVersion = completed.find(g => g.id === referenceGeneration);
  const chosenAsset = assets.find(a => a.id === chosenVersion?.assetIds[0] && a.project_id === projectId);

  async function pin() {
    const target = boards.find(b => b.id === referenceTarget);
    if (!selected || !target || !chosenVersion || !chosenAsset) return;
    const previous = target.settings.references.find(r => r.sourceBoardId === selected.id);
    if (previous && !confirm(`Update ${target.name}'s pinned note to this explicitly chosen version? Already submitted generations keep the old version.`)) return;
    const ref: VisualReference = { id: previous?.id ?? crypto.randomUUID(), sourceBoardId: selected.id, sourceGenerationId: chosenVersion.id, assetId: chosenAsset.id, assetVersionId: chosenAsset.content_hash, role: "visual-note" };
    if (await props.onSettings(target, { ...target.settings, references: previous ? target.settings.references.map(r => r.id === previous.id ? ref : r) : [...target.settings.references, ref] })) { setReferenceGeneration(""); setReferenceTarget(""); }
    else setError("The target board could not save this visual note. Your version selection is retained; refresh and retry.");
  }

  if (!selected) return <div className="canvas-panel-empty"><Layers3 size={28} /><h3>Choose a board</h3><p>Select a board to see its composition, settings and saved versions.</p></div>;
  if (isImageRecipeBoard(selected)) return <ImageRecipeControls board={selected} assets={assets} onChange={async next => { if (!await props.onSettings(selected, next)) throw new Error("Image settings could not save; refresh before retrying."); }} onError={setError} />;
  if (isVideoBoard(selected)) return <VideoBoardControls board={selected} assets={assets} onChange={async next => { if (!await props.onSettings(selected, next)) throw new Error("Video settings could not save; refresh before retrying."); }} onError={setError} />;
  const profile = canvasProfiles[selected.settings.adapterVersion];
  return <section className="moss-inspector" aria-label="Selected board"><header><div><small>Selected board</small><strong>{selected.name}</strong></div></header>
    <label>Board name<input key={`${selected.id}:${selected.name}`} defaultValue={selected.name} maxLength={200} onBlur={async e => { const name = e.target.value.trim(); if (!name || name === selected.name) return; try { await prepareBoard(projectId, selected); const doc = await canvasApi.get(projectId, selected.documentId); await canvasApi.save(projectId, selected.documentId, doc.revision, { ...doc.content, name }); refresh(); } catch (error) { props.setBoardError(selected.id, errorText(error)); } }} /></label>
    <p className="canvas-help">{profile.family} · {profile.name}</p>
    <CanvasProfileControls board={selected} onChange={next => props.onSettings(selected, next)} onError={setError} />
    <label>Saved composition prompt<textarea readOnly value={versions.data?.content.globalPrompt ?? selected.prompt} rows={4} /><small>Edit the prompt in the focused editor.</small></label>
    <div className="canvas-composition-summary"><span>{selected.artboard.width} × {selected.artboard.height}</span><span>{selected.regionCount} regions</span></div>
    {selected.activeResult ? <p className="canvas-help">Showing result r{selected.activeResult.revision}{selected.documentRevision !== selected.activeResult.revision ? ` · Layout r${selected.documentRevision} has newer edits` : ""}{selected.newResult ? " · New result in History" : ""}</p> : null}
    <button className="secondary-button" disabled={selected.archived} onClick={() => props.onOpen(selected)}>Open focused editor <ArrowRight size={14} /></button>
    <button className="primary-button moss-panel-generate" disabled={!props.canGenerate} onClick={() => props.onGenerate(selected)}><Sparkles size={15} />{props.generateLabel}</button>
    <p className="canvas-help" role="status">{props.status}{selected.jobs[0] ? ` · ${selected.jobs[0].statusMessage}` : props.preparing ? " · Saving and validating this composition" : ""}</p>
    <button className="secondary-button" disabled={props.creating || selected.archived} onClick={() => props.onDuplicate(selected)}><Copy size={14} />Duplicate board</button>
    <details className="canvas-board-settings"><summary>Generation settings & arrangement</summary>
      {placement ? <details className="moss-card-placement"><summary>Workspace position &amp; card size</summary><p className="canvas-help">Presentation only. The output remains {selected.artboard.width} × {selected.artboard.height}.</p>
        {(["x", "y", "displayWidth", "displayHeight"] as const).map(key => <label key={`${selected.id}:${key}:${placement[key]}`}>{key}<input type="number" defaultValue={Math.round(placement[key])} onBlur={e => { const value = Number(e.target.value); if (!Number.isFinite(value)) return; const min = key === "displayWidth" ? 280 : key === "displayHeight" ? 350 : -100000, max = key === "displayWidth" ? 800 : key === "displayHeight" ? 900 : 100000; props.onMove({ ...placement, [key]: Math.max(min, Math.min(max, value)) }); }} /></label>)}</details> : null}
      <button className="text-button" onClick={() => props.onFitArtwork(selected)}><Maximize size={14} />Fit card to artwork proportions</button>
      <button className="text-button" onClick={() => props.onJump(selected)}>Fit selected board</button>
      <button className="text-button" onClick={async () => { if (!confirm(selected.archived ? "Restore this board?" : "Archive this board? Its document, assets and pending jobs are retained.")) return; try { await mossApi.save(projectId, selected, selected.settings, !selected.archived); refresh(); props.onArchived(); } catch (e) { setError(errorText(e)); } }}>{selected.archived ? "Restore to workspace" : "Archive from workspace"}</button>
    </details>
    {selected.jobs.map(j => <div className="moss-job" key={j.id}><strong>{j.status === "queued" ? "Queued" : j.statusMessage} · r{j.revision}</strong>{j.status === "queued" ? <button onClick={() => void mossApi.cancel(projectId, selected.id, j.jobId).then(refresh).catch(e => setError(errorText(e)))}>Cancel queued job</button> : <small>Running work is not globally interrupted.</small>}</div>)}
    {selected.jobs.some(j => j.status === "queued") ? <button className="text-button" onClick={async () => { const j = selected.jobs.find(j => j.status === "queued"); if (j) { try { await canvasApi.start(projectId, selected.documentId, j.id); refresh(); } catch (e) { setError(errorText(e)); } } }}>Wake shared worker</button> : null}
    {props.error ? <p className="form-error" role="alert">{props.error}</p> : null}
    {selected.activeResult?.assetIds[0] ? <details className="h3-transfer"><summary>Use in video board</summary>
      <label>Video board<select value={videoTarget} onChange={e => setVideoTarget(e.target.value)}><option value="new">Create a new Video board</option>{boards.filter(b => isVideoBoard(b) && !b.archived).map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
      <label>Input role<select value={videoRole} onChange={e => setVideoRole(e.target.value as VideoRole)}><option value="animate-image">Starting frame</option><option value="camera-direction">Camera source</option><option value="reference-video">Reference image</option></select></label>
      <button className="secondary-button" onClick={() => props.onBindVideo(selected, videoTarget, videoRole)}>Pin this exact image version</button><small>Only binds the selected result. Generate when ready.</small></details> : null}
    <details className="moss-references"><summary>Pinned visual notes</summary><p className="canvas-help">Visual reference — not sent to MOSS. Connections never queue work.</p>
      {selected.settings.references.map(ref => { const source = boards.find(b => b.id === ref.sourceBoardId), newer = source?.latest?.status === "completed" && source.latest.id !== ref.sourceGenerationId; return <div className="moss-reference" key={ref.id}><VisualNoteThumbnail assetId={ref.assetId} /><strong>{source?.name ?? "Archived source"}</strong><small>Version {ref.sourceGenerationId.slice(0,8)} · {ref.assetVersionId.slice(0,12)}</small>{newer ? <small>New version available · select it explicitly on the source board to update this note.</small> : null}<button className="text-button" onClick={() => { if (source) props.onJump(source); }}>Jump to source</button><button className="text-button" onClick={() => void props.onSettings(selected, { ...selected.settings, references: selected.settings.references.filter(r => r.id !== ref.id) })}>Remove connection</button></div>; })}</details>
    <details className="moss-pin"><summary>Pin a completed result</summary>
      <label>Exact result version<select value={referenceGeneration} onChange={e => setReferenceGeneration(e.target.value)}><option value="">Choose a version…</option>{completed.map(g => <option value={g.id} key={g.id}>r{g.revision} · seed {g.seed} · {g.createdAt.slice(0,16)}</option>)}</select></label>
      {chosenAsset ? <><img alt="Chosen immutable reference version" src={api.assetContentUrl(chosenAsset.id)} /><small>Asset {chosenAsset.id.slice(0,8)} · hash {chosenAsset.content_hash.slice(0,12)}</small><button className="text-button" onClick={async () => { if (chosenVersion) { await canvasApi.select(projectId, selected.documentId, chosenVersion.id); refresh(); } }}>Display this result on source board</button></> : null}
      <label>Target board<select value={referenceTarget} onChange={e => setReferenceTarget(e.target.value)}><option value="">Choose another board…</option>{boards.filter(b => b.id !== selected.id && !b.archived).map(b => <option value={b.id} key={b.id}>{b.name}</option>)}</select></label>
      <button className="secondary-button" disabled={!chosenAsset || !referenceTarget} onClick={() => void pin()}>Confirm visual reference</button></details>
  </section>;
}

export function BoardHistory({ projectId, selected, setError, refresh }: { projectId: string; selected: MossBoard | undefined; setError: (message: string) => void; refresh: () => void }) {
  const versions = useBoardVersions(projectId, selected);
  if (!selected) return <div className="canvas-panel-empty"><p>Select a board to browse its saved results.</p></div>;
  return <section className="canvas-board-history"><h3>{selected.name} · versions</h3>
    <div className="canvas-draft-entry"><Layers3 size={18} /><div><strong>Draft r{versions.data?.revision ?? selected.documentRevision}</strong><small>Saved layout · {selected.activeResult && selected.activeResult.revision !== selected.documentRevision ? "newer edits than the displayed result" : "current composition"}</small></div></div>
    {versions.isLoading ? <p>Loading versions…</p> : null}{versions.isError ? <p role="alert">Versions could not load. <button onClick={() => void versions.refetch()}>Retry</button></p> : null}
    {versions.data?.generations.map(result => <div className="canvas-version" key={result.id}><button type="button" disabled={result.status !== "completed"} aria-pressed={selected.activeResult?.id === result.id} onClick={async () => { try { await canvasApi.select(projectId, selected.documentId, result.id); refresh(); void versions.refetch(); } catch (error) { setError(errorText(error)); } }}>
      {result.assetIds[0] ? <VisualNoteThumbnail assetId={result.assetIds[0]} /> : <Layers3 size={20} />}<span>Result from r{result.revision}<small>{result.status} · seed {result.seed}</small><small>{result.createdAt.slice(0,16).replace("T", " ")}</small></span></button>
      <CanvasGenerationDetails result={result} board={selected} projectId={projectId} generations={versions.data?.generations ?? []} onError={setError} />{result.error ? <p>{result.error}</p> : null}</div>)}
    {!versions.isLoading && !versions.data?.generations.length ? <p>No generated versions yet.</p> : null}
  </section>;
}
