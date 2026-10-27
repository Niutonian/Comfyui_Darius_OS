"use client";
/* eslint-disable @next/next/no-img-element -- local immutable asset previews */
import { createPortal } from "react-dom";
import { Images } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { api } from "@/lib/api-client";
import { useDariusStore } from "@/lib/store";
import type { Asset } from "@/lib/types";
import { assetName } from "@/lib/chat-labels";

export function AssistantReferences({ projectId, busy, triggerHost }: { projectId: string; busy: boolean; triggerHost?: HTMLSpanElement | null }) {
  const { referenceAssetIds, addReferenceAsset, removeReferenceAsset } = useDariusStore();
  const pickerId = useId();
  const [open, setOpen] = useState(false);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void api.assets({ project_id: projectId, kind: "image", limit: 100 }).then((items) => {
      if (!cancelled) setAssets(items.filter((a) => a.role !== "derivative"));
    }).catch((err: Error) => { if (!cancelled) setError(err.message); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, projectId]);
  const label = `Choose project images${referenceAssetIds.length ? ` \u00b7 ${referenceAssetIds.length} selected` : ""}`;
  const trigger = <button className={triggerHost ? "icon-button project-images-trigger" : "secondary-button"} aria-label={label} title="Choose project images" aria-controls={open ? pickerId : undefined} type="button" disabled={busy} aria-expanded={open} onClick={() => { if (!open) { setLoading(true); setError(""); } setOpen(!open); }}>{triggerHost ? <><Images size={18} />{referenceAssetIds.length ? <span className="reference-count">{referenceAssetIds.length}</span> : null}</> : label}</button>;
  return <div className="assistant-references">
    {triggerHost ? createPortal(trigger, triggerHost) : trigger}
    {referenceAssetIds.length ? <div className="reference-strip">{referenceAssetIds.map((id) => <span key={id}><img src={api.assetContentUrl(id)} alt={`Reference ${id.slice(0, 8)}`} /><button type="button" disabled={busy} aria-label={`Remove reference ${id.slice(0, 8)}`} onClick={() => removeReferenceAsset(id)}>×</button></span>)}</div> : null}
    {open ? <div className="reference-picker" id={pickerId} role="region" aria-label="Project images">
      <label>Find a project image<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filename or image ID" /></label>
      <small>Select up to four, then describe what to do by voice or text. You can also ask Darius to find images by their subject.</small>
      {loading ? <p role="status">Loading images…</p> : null}{error ? <p role="alert">{error}</p> : null}
      <div className="reference-options">{assets.filter((asset) => `${asset.id} ${assetName(asset)} ${asset.metadata.original_filename ?? ""}`.toLowerCase().includes(query.toLowerCase())).map((asset) => <button key={asset.id} type="button" aria-pressed={referenceAssetIds.includes(asset.id)} aria-label={`Use image ${assetName(asset)}`} disabled={busy || (!referenceAssetIds.includes(asset.id) && referenceAssetIds.length >= 4)} onClick={() => referenceAssetIds.includes(asset.id) ? removeReferenceAsset(asset.id) : addReferenceAsset(asset.id)}><img loading="lazy" src={api.assetContentUrl(asset.id)} alt="" /><span>{assetName(asset)}</span></button>)}</div>
      {!loading && !error && !assets.length ? <p>No project images yet.</p> : null}
    </div> : null}
  </div>;
}

export function ConversationImages({ ids }: { ids: unknown }) {
  if (!Array.isArray(ids)) return null;
  return <div className="reference-strip">{ids.filter((id): id is string => typeof id === "string").slice(0, 8).map((id) => <button className="conversation-image" key={id} type="button" onClick={() => {
    useDariusStore.getState().addReferenceAsset(id);
  }} title="Use this image as a reference"><img loading="lazy" src={api.assetContentUrl(id)} alt={`Image ${id.slice(0, 8)}`} /><small>{id.slice(0, 8)}</small></button>)}</div>;
}
