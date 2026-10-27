"use client";
/* eslint-disable @next/next/no-img-element -- original local media is served by the asset API */

import { ChevronLeft, ChevronRight, Maximize2, X, Play, Pause, Square, RotateCcw, Volume2, VolumeX, Images } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";
import type { Asset } from "@/lib/types";
import { MediaPreview } from "./media-preview";
import { assetName } from "@/lib/chat-labels";
import type { PlaybackControl } from "@/lib/use-asset-presentation";

export function AssetPreview({ asset, compact = false, navigationAssets }: { asset: Asset; compact?: boolean; navigationAssets?: Asset[] }) {
  const [open, setOpen] = useState(false);
  const [viewerAsset, setViewerAsset] = useState(asset);
  const [sourceAssetId, setSourceAssetId] = useState(asset.id);
  if (asset.id !== sourceAssetId) {
    setSourceAssetId(asset.id);
    setViewerAsset(asset);
  }
  return <div className="expandable-asset">
    {asset.kind === "image" || compact ? <button className="asset-preview-trigger" aria-label={`Preview ${asset.kind} ${assetName(asset)} full size`} onClick={() => { setViewerAsset(asset); setOpen(true); }} type="button"><MediaPreview asset={asset} compact /><span className="asset-expand-label"><Maximize2 size={15} /> Full size</span></button> : <><MediaPreview asset={asset} /><button className="asset-expand-label" aria-label={`Preview ${asset.kind} ${assetName(asset)} full size`} onClick={() => { setViewerAsset(asset); setOpen(true); }} type="button"><Maximize2 size={15} /> Full size</button></>}
    {open ? <AssetViewer asset={viewerAsset} navigationAssets={navigationAssets ?? [asset]} onSelect={setViewerAsset} onClose={() => setOpen(false)} /> : null}
  </div>;
}

export function AssetViewer({ asset, navigationAssets = [asset], onSelect, onClose, playback, onGallery }: { asset: Asset; navigationAssets?: Asset[]; onSelect: (asset: Asset) => void; onClose: () => void; playback?: PlaybackControl | null; onGallery?: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; }, [onClose]);
  const assets = navigationAssets.filter((item) => item.project_id === asset.project_id);
  const index = assets.findIndex((item) => item.id === asset.id);
  useEffect(() => {
    const element = dialog.current;
    const focus = document.activeElement as HTMLElement | null;
    element?.showModal();
    return () => { if (element?.open) element.close(); if (focus?.isConnected) focus.focus(); };
  }, []);
  return <dialog ref={dialog} className="asset-viewer" aria-label={`Full-size preview: ${assetName(asset)}`}
    onCancel={(event) => { event.preventDefault(); event.stopPropagation(); close.current(); }} onClose={(event) => { event.stopPropagation(); if (event.currentTarget.isConnected && !event.currentTarget.open) close.current(); }}
    onKeyDown={(event) => {
      if (event.target instanceof HTMLMediaElement || (event.target instanceof HTMLElement && ["INPUT", "TEXTAREA"].includes(event.target.tagName))) return;
      if (event.key === "ArrowLeft" && index > 0) { event.preventDefault(); onSelect(assets[index - 1]); }
      if (event.key === "ArrowRight" && index >= 0 && index < assets.length - 1) { event.preventDefault(); onSelect(assets[index + 1]); }
    }}>
    <AssetViewerContent key={asset.id} asset={asset} playback={playback} onGallery={onGallery} onClose={onClose} previousDisabled={index <= 0} nextDisabled={index < 0 || index === assets.length - 1} onPrevious={() => { if (index > 0) onSelect(assets[index - 1]); }} onNext={() => { if (index >= 0 && index < assets.length - 1) onSelect(assets[index + 1]); }} />
  </dialog>;
}

function AssetViewerContent({ asset, onClose, previousDisabled, nextDisabled, onPrevious, onNext, playback, onGallery }: { asset: Asset; onClose: () => void; previousDisabled: boolean; nextDisabled: boolean; onPrevious: () => void; onNext: () => void; playback?: PlaybackControl | null; onGallery?: () => void }) {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const media = useRef<HTMLMediaElement | null>(null);
  const applied = useRef<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [notice, setNotice] = useState("");
  const playable = asset.kind === "video" || asset.kind === "audio";
  async function control(action: PlaybackControl["action"], seconds = 0) {
    const element = media.current;
    if (!element) return;
    setNotice("");
    try {
      if (action === "play" || action === "restart") {
        if (action === "restart") element.currentTime = 0;
        await element.play();
      } else if (action === "pause" || action === "stop") {
        element.pause();
        if (action === "stop") element.currentTime = 0;
      } else if (action === "mute" || action === "unmute") {
        element.muted = action === "mute"; setMuted(element.muted);
      } else if (action === "seek") {
        const duration = Number.isFinite(element.duration) ? element.duration : 0;
        if (!duration) { setNotice("The video is still loading. Try seeking again once it is ready."); return; }
        element.currentTime = Math.max(0, Math.min(duration, element.currentTime + seconds));
      }
    } catch { if (media.current === element) setNotice("Your browser blocked playback or the media is unavailable. Tap Play to try again."); }
  }
  const command = useRef(control);
  useEffect(() => { command.current = control; });
  useEffect(() => {
    if (playback && playback.assetId === asset.id && playback.id !== applied.current) {
      applied.current = playback.id;
      void command.current(playback.action, playback.seconds);
    }
  }, [playback, asset.id]);
  useEffect(() => {
    const element = media.current;
    return () => { element?.pause(); };
  }, []);
  const url = api.assetContentUrl(asset.id);
  const name = assetName(asset);
  return <>
    <header className="asset-viewer-toolbar"><div><strong>{name}</strong><span>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : asset.kind}{asset.duration ? ` · ${asset.duration.toFixed(1)}s` : ""}</span></div><div className="asset-viewer-actions">{onGallery ? <button aria-label="Back to gallery" className="icon-button" onClick={onGallery} title="Back to gallery" type="button"><Images size={20} /></button> : null}<button aria-label="Previous asset" className="icon-button" disabled={previousDisabled} onClick={onPrevious} title="Previous asset" type="button"><ChevronLeft size={21} /></button><button aria-label="Next asset" className="icon-button" disabled={nextDisabled} onClick={onNext} title="Next asset" type="button"><ChevronRight size={21} /></button><button aria-label="Close asset preview" className="icon-button" onClick={onClose} type="button"><X size={21} /></button></div></header>
    <div className="asset-viewer-stage fit-size">
      {status === "loading" ? <p className="asset-viewer-status" role="status">Loading preview…</p> : null}
      {status === "error" ? <p className="asset-viewer-status" role="alert">This asset could not be loaded. Close the preview and try again.</p> : null}
      {asset.kind === "image" ? <img alt={name} src={url} onLoad={() => setStatus("ready")} onError={() => setStatus("error")} /> : asset.kind === "video" ? <video ref={element => { media.current = element; }} aria-label={name} src={url} controls playsInline preload="metadata" onPlay={() => { setPlaying(true); setNotice(""); }} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onVolumeChange={() => setMuted(Boolean(media.current?.muted))} onLoadedData={() => setStatus("ready")} onError={() => setStatus("error")} /> : asset.kind === "audio" ? <audio ref={element => { media.current = element; }} aria-label={name} src={url} controls preload="metadata" onPlay={() => { setPlaying(true); setNotice(""); }} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onVolumeChange={() => setMuted(Boolean(media.current?.muted))} onLoadedMetadata={() => setStatus("ready")} onError={() => setStatus("error")} /> : <p>Preview is not available for this asset type.</p>}
    </div>
    {playable ? <div className="asset-playback-controls"><button type="button" className="secondary-button" onClick={() => void control(playing ? "pause" : "play")}>{playing ? <Pause size={16} /> : <Play size={16} />}{playing ? "Pause" : "Play"}</button><button type="button" className="secondary-button" onClick={() => void control("stop")}><Square size={14} />Stop</button><button type="button" className="secondary-button" onClick={() => void control("restart")}><RotateCcw size={15} />Restart</button><button type="button" className="secondary-button" onClick={() => void control(muted ? "unmute" : "mute")}>{muted ? <VolumeX size={16} /> : <Volume2 size={16} />}{muted ? "Unmute" : "Mute"}</button><span role="status">{notice || (playback ? "Voice controls: play, pause, stop, restart, mute, skip forward ten seconds." : "")}</span></div> : null}
    <footer className="asset-viewer-footer">Original asset<span>Esc to close</span></footer>
  </>;
}
