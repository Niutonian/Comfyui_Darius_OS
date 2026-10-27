"use client";
import { useEffect, useRef, useState } from "react";
import { X, Search, ImageIcon } from "lucide-react";
import type { Asset } from "@/lib/types";
import { assetName } from "@/lib/chat-labels";
import { MediaPreview } from "./media-preview";

/** Numbers stay stable while searching: speech always refers to the displayed card. */
export function VoiceGallery({ assets, onSelect, onClose }: { assets: Asset[]; onSelect: (asset: Asset) => void; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState("");
  useEffect(() => {
    const element = dialog.current, focus = document.activeElement as HTMLElement | null;
    element?.showModal();
    return () => { if (element?.open) element.close(); if (focus?.isConnected) focus.focus(); };
  }, []);
  return <dialog ref={dialog} className="asset-viewer voice-gallery" aria-label="Project media gallery" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }} onClose={event => { event.stopPropagation(); if (event.currentTarget.isConnected && !event.currentTarget.open) onClose(); }}>
    <header className="asset-viewer-toolbar"><div><strong><ImageIcon size={16} aria-hidden /> Project gallery</strong><span>Newest first · up to 48 recent items</span></div><button type="button" className="icon-button" aria-label="Close gallery" onClick={onClose}><X size={22} /></button></header>
    <p className="voice-gallery-hint">Say “open image three”, “select Forest opening”, or “play video two”. Numbers identify cards, including when you search. Say “close gallery” to return.</p>
    <label className="voice-gallery-search"><Search size={16} /><span className="sr-only">Search gallery</span><input aria-label="Search gallery" value={query} onChange={event => setQuery(event.target.value)} placeholder="Find a saved name…" /></label>
    <div className="voice-gallery-grid">{assets.map((asset, index) => !query || assetName(asset).toLocaleLowerCase().includes(query.toLocaleLowerCase()) ? <button type="button" key={asset.id} aria-label={`Open ${asset.kind} ${index + 1}: ${assetName(asset)}`} onClick={() => onSelect(asset)}><span className="voice-gallery-media"><MediaPreview asset={asset} compact /><b>{index + 1}</b><small>{asset.kind}</small></span><strong>{assetName(asset)}</strong></button> : null)}
      {assets.every(asset => query && !assetName(asset).toLocaleLowerCase().includes(query.toLocaleLowerCase())) ? <p>No names match. Clear search or ask Darius to open a saved image by name.</p> : null}
    </div>
    <footer className="asset-viewer-footer">{assets.length} saved {assets.length === 1 ? "item" : "items"} · active project only<span>Esc to close</span></footer>
  </dialog>;
}
