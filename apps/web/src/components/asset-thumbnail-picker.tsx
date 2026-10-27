"use client";
import { useId, useState } from "react";
import { Check } from "lucide-react";
import type { Asset } from "@/lib/types";
import { assetName } from "@/lib/chat-labels";
import { MediaPreview } from "./media-preview";

export function AssetThumbnailPicker({ label, assets, projectId, value, onChange }: { label: string; assets: Asset[]; projectId: string; value: string; onChange: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const id = useId();
  const owned = assets.filter(asset => asset.project_id === projectId && asset.role !== "derivative");
  const filtered = owned.filter(asset => assetName(asset).toLowerCase().includes(query.trim().toLowerCase()));
  return <div className="asset-thumbnail-picker" role="group" aria-labelledby={id}>
    <strong id={id}>{label}</strong>
    {owned.length > 6 ? <label className="thumbnail-search">Find media<input aria-label={`Find ${label.toLowerCase()}`} placeholder="Search by name" value={query} onChange={event => setQuery(event.target.value)} /></label> : null}
    <div className="asset-thumbnail-options">{filtered.map(asset => <button className={value === asset.id ? "is-selected" : ""} key={asset.id} type="button" aria-label={`${label}: ${assetName(asset)}`} aria-pressed={value === asset.id} onClick={() => onChange(value === asset.id ? "" : asset.id)}><span className="thumbnail-media"><MediaPreview asset={asset} compact />{value === asset.id ? <i><Check size={15} /></i> : null}</span><span title={assetName(asset)}>{assetName(asset)}</span><small>{asset.kind}</small></button>)}</div>
    {!filtered.length ? <small>{owned.length ? "No media matches this search." : "No available project media yet."}</small> : null}
  </div>;
}
