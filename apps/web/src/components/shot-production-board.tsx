"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import type { Asset, ShotBoardEntry, ShotProductionUpdate } from "@/lib/types";
import { queryKeys } from "@/lib/queries";
import { useDariusStore } from "@/lib/store";
import { AssetPreview } from "./asset-preview";
import { ProductionStructure } from "./production-structure";
import { Clapperboard } from "lucide-react";
import { assetName } from "@/lib/chat-labels";
import { AssetThumbnailPicker } from "./asset-thumbnail-picker";
import { useWorkspaceState } from "@/lib/workspace-session";

const name = assetName;

export function ShotProductionBoard({ projectId, assets }: { projectId: string; assets: Asset[] }) {
  const [scene, setScene] = useWorkspaceState(`shots:${projectId}:scene`, "all");
  const [status, setStatus] = useWorkspaceState(`shots:${projectId}:status`, "all");
  const board = useQuery({ queryKey: ["shot-board", projectId], queryFn: () => api.shotBoard(projectId), refetchInterval: 5000 });
  const rows = board.data ?? [];
  const scenes = [...new Map(rows.map(row => [row.shot.scene_id, row])).values()];
  return <section className="shot-production-board" aria-label="Shot production board">
    <header className="view-heading"><div><span className="eyebrow">Production</span><h2>Shot production board</h2><p>References, generations, chosen takes and readiness—one place per shot.</p></div><span>{rows.filter(row => row.takes.some(asset => asset.id === row.shot.selected_asset_id)).length} / {rows.length} shots have a chosen take</span></header>
    <div className="control-row"><label>Board scene<select value={scene} onChange={event => setScene(event.target.value)}><option value="all">All scenes</option>{scenes.map(row => <option key={row.shot.scene_id} value={row.shot.scene_id}>Scene {row.scene_number} · {row.scene_title}</option>)}</select></label><label>Board status<select value={status} onChange={event => setStatus(event.target.value)}><option value="all">All statuses</option>{["planned", "ready", "generated", "selected", "complete"].map(value => <option key={value} value={value}>{value}</option>)}</select></label></div>
    {board.isLoading ? <p role="status">Loading shot production…</p> : null}
    {board.isError ? <p role="alert">Could not load the board. <button className="secondary-button" onClick={() => void board.refetch()} type="button">Retry board</button></p> : null}
    {!board.isLoading && !board.isError && !rows.length ? <p>Create scenes and shots in “Manage scenes & shots” below to start your board.</p> : null}
    <div className="shot-board-grid">{rows.filter(row => (scene === "all" || row.shot.scene_id === scene) && (status === "all" || row.shot.status === status)).map(row => <ShotCard key={projectId + row.shot.id} row={row} projectId={projectId} assets={assets.filter(asset => asset.project_id === projectId && asset.role !== "derivative")} />)}</div>
    <details className="shot-board-records"><summary>Manage scenes & shots</summary><ProductionStructure projectId={projectId} assets={assets} focus="shots" /></details>
  </section>;
}

function ShotCard({ row, projectId, assets }: { row: ShotBoardEntry; projectId: string; assets: Asset[] }) {
  const client = useQueryClient();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [reference, setReference] = useState("");
  const [take, setTake] = useState("");
  const takes = row.takes.filter(asset => asset.project_id === projectId);
  const references = row.references.filter(asset => asset.project_id === projectId);
  const chosen = takes.find(asset => asset.id === row.shot.selected_asset_id);
  const preview = chosen ?? [...takes].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? references[0];
  async function update(payload: ShotProductionUpdate) {
    setSaving(true); setError("");
    try {
      await api.updateShotProduction(projectId, row.shot.id, payload);
      await Promise.all([client.invalidateQueries({ queryKey: ["shot-board", projectId] }), client.invalidateQueries({ queryKey: queryKeys.shots(row.shot.scene_id) })]);
      setReference(""); setTake("");
    } catch (error) { setError(error instanceof Error ? error.message : "Could not save this shot."); }
    finally { setSaving(false); }
  }
  async function focus() {
    setSaving(true); setError("");
    try {
      const memory = await api.assistantContext(projectId);
      await api.saveAssistantContext(projectId, { ...memory, scene_id: row.shot.scene_id, shot_id: row.shot.id, reference_asset_ids: references.map(asset => asset.id) });
      const store = useDariusStore.getState();
      if (store.activeProjectId !== projectId) return;
      // Replace explicitly selected references instead of carrying another shot's images.
      for (const id of store.referenceAssetIds) store.removeReferenceAsset(id);
      for (const asset of references) store.addReferenceAsset(asset.id);
      store.setView("talk");
    } catch (error) { setError(error instanceof Error ? error.message : "Could not focus this shot."); }
    finally { setSaving(false); }
  }
  return <article className="shot-board-card" aria-label={`Scene ${row.scene_number} shot ${row.shot.number}`}>
    <div className="shot-card-thumbnail">{preview ? <AssetPreview asset={preview} compact navigationAssets={takes.length ? takes : references} /> : <div className="shot-thumbnail-empty"><Clapperboard size={30} aria-hidden /><span>No media yet</span></div>}<span className="shot-thumbnail-badge">{chosen ? "Chosen take" : takes.length ? "Latest take" : preview ? "Reference" : "Planned"}</span></div>
    <header><span className="eyebrow">Scene {row.scene_number} · {row.scene_title}</span><div className="shot-card-title"><h3>Shot {row.shot.number}</h3><span className={`shot-readiness readiness-${row.shot.status}`}>{row.shot.status}</span></div><p title={row.shot.description}>{row.shot.description || "No shot description yet"}</p><small>{row.shot.shot_type || "Shot type unset"} · {row.shot.duration_target}s · {takes.length} take{takes.length === 1 ? "" : "s"}</small></header>
    <button className="primary-button shot-focus-button" disabled={saving} onClick={() => void focus()} type="button">Work with Darius on this shot</button>
    <details className="shot-card-details"><summary>Shot details & media</summary>
    <fieldset disabled={saving}><label>Readiness<select value={row.shot.status} onChange={event => void update({ status: event.target.value as ShotProductionUpdate["status"] })}>{["planned", "ready", "generated", "selected", "complete"].map(value => <option key={value} value={value} disabled={(value === "selected" || value === "complete") && !chosen}>{value}</option>)}</select></label>
    {!chosen && ["selected", "complete"].includes(row.shot.status) ? <p className="form-error">Chosen media is unavailable. Choose another take or reset readiness.</p> : null}
    <section><h4>References · {references.length}/4</h4><div className="shot-board-media">{references.map(asset => <div key={asset.id}><AssetPreview asset={asset} compact /><small>{name(asset)}</small><button className="text-button" onClick={() => void update({ reference_asset_ids: references.filter(item => item.id !== asset.id).map(item => item.id) })} type="button">Unpin reference</button></div>)}</div><AssetThumbnailPicker label="Add reference" assets={assets.filter(asset => asset.kind === "image" && !references.some(item => item.id === asset.id))} projectId={projectId} value={reference} onChange={setReference} /><button className="secondary-button" disabled={!reference || references.length >= 4} onClick={() => void update({ reference_asset_ids: [...references.map(asset => asset.id), reference] })} type="button">Pin reference</button></section>
    <section><h4>Chosen take</h4>{chosen ? <><p>{name(chosen)}</p><button className="text-button" onClick={() => void update({ selected_asset_id: null, status: takes.length ? "generated" : "planned" })} type="button">Clear chosen take</button></> : <p>No take chosen yet.</p>}</section>
    <details><summary>Generations & takes · {takes.length}</summary><div className="shot-board-media">{takes.map(asset => <div key={asset.id}><AssetPreview asset={asset} compact /><small>{name(asset)}</small><button className="secondary-button" disabled={asset.id === chosen?.id} onClick={() => void update({ selected_asset_id: asset.id, status: "selected" })} type="button">{asset.id === chosen?.id ? "Chosen" : "Choose take"}</button></div>)}</div></details>
    <AssetThumbnailPicker label="Link existing take" assets={assets.filter(asset => ["image", "video"].includes(asset.kind) && !takes.some(item => item.id === asset.id))} projectId={projectId} value={take} onChange={setTake} /><button className="secondary-button" disabled={!take} onClick={() => void update({ take_asset_ids: [...takes.map(asset => asset.id), take] })} type="button">Link take</button>
    {row.jobs.map(job => <button className="text-button" key={job.id} onClick={() => useDariusStore.getState().setSelection({ type: "job", id: job.id })} type="button">{job.status} · {job.status_message}</button>)}
    <small>Focuses this shot and its references. New generations are tracked here; nothing is rendered by the focus button.</small></fieldset><button className="secondary-button" type="button" onClick={event => { const details = event.currentTarget.closest<HTMLDetailsElement>("details.shot-card-details"); if (details) { details.open = false; details.querySelector<HTMLElement>("summary")?.focus({ preventScroll: true }); details.closest("article")?.scrollIntoView({ block: "nearest" }); } }}>Back to shot board</button></details>
    {error ? <p role="alert" className="form-error">{error}</p> : null}
  </article>;
}
