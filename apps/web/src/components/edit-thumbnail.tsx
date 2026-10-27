"use client";
/* eslint-disable @next/next/no-img-element -- thumbnails are project-scoped local media */
import { Film, Music2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";
import type { Asset } from "@/lib/types";

const posters = new Map<string, string>();
const pending = new Map<string, Promise<string>>();
let queue = Promise.resolve();
// Decode one small poster at a time, then release the media element; no grid of live video decoders.
function poster(asset: Asset): Promise<string> {
  const cached = posters.get(asset.id); if (cached) return Promise.resolve(cached);
  const existing = pending.get(asset.id); if (existing) return existing;
  const work = queue.then(() => new Promise<string>((resolve) => {
    const video = document.createElement("video");
    let finished = false;
    const finish = (url = "") => {
      if (finished) return; finished = true; clearTimeout(timeout);
      video.onloadeddata = null; video.onseeked = null; video.onerror = null;
      video.pause(); video.removeAttribute("src"); video.load();
      if (url) { if (posters.size >= 100) posters.delete(posters.keys().next().value!); posters.set(asset.id, url); }
      resolve(url);
    };
    const capture = () => {
      try {
        const canvas = document.createElement("canvas"), scale = 256 / Math.max(video.videoWidth, video.videoHeight);
        canvas.width = Math.max(1, Math.round(video.videoWidth * scale)); canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
        canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
        finish(canvas.toDataURL("image/jpeg", .7));
      } catch { finish(); }
    };
    const timeout = setTimeout(() => finish(), 6000);
    video.muted = true; video.playsInline = true; video.preload = "auto";
    video.onerror = () => finish(); video.onseeked = capture;
    video.onloadeddata = () => { if (video.duration > .2) video.currentTime = .1; else capture(); };
    video.src = api.assetContentUrl(asset.id); video.load();
  }));
  pending.set(asset.id, work); queue = work.then(() => {});
  void work.finally(() => pending.delete(asset.id)); return work;
}

export function EditThumbnail({ asset, assets }: { asset?: Asset; assets: Asset[] }) {
  const target = useRef<HTMLSpanElement>(null);
  const [captured, setCaptured] = useState({ id: "", url: "" });
  const image = captured.id === asset?.id ? captured.url : "";
  const derivative = asset && assets.find((item) => item.project_id === asset.project_id && item.role === "derivative" && item.kind === "image" && item.parent_asset_ids.includes(asset.id) && item.metadata.derivative_type === "thumbnail");
  const direct = derivative ?? (asset?.kind === "image" ? asset : undefined);
  useEffect(() => {
    if (!asset || asset.kind !== "video" || direct) return;
    let cancelled = false;
    const load = () => { if (!cancelled) void poster(asset).then((url) => { if (!cancelled) setCaptured({ id: asset.id, url }); }); };
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { observer.disconnect(); load(); } });
    if (target.current) observer.observe(target.current);
    return () => { cancelled = true; observer.disconnect(); };
  }, [asset, direct]);
  return <span className="desk-thumbnail" ref={target}>{direct || image ? <img alt="" loading="lazy" src={direct ? api.assetContentUrl(direct.id) : image} /> : asset?.kind === "audio" ? <Music2 size={22} /> : <Film size={22} />}</span>;
}
