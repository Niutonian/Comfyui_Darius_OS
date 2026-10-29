"use client";
/* eslint-disable @next/next/no-img-element -- project-owned media */
import type { RefObject } from "react";
import { api } from "@/lib/api-client";
import type { Asset } from "@/lib/types";
export function ProjectImagePicker({ assets, projectId, onChoose, pickerRef, mediaKind = "image" }: { assets: Asset[]; projectId: string; onChoose: (asset: Asset) => void; pickerRef?: RefObject<HTMLDivElement | null>; mediaKind?: "image" | "video" }) {
 const images = assets.filter(asset => asset.project_id === projectId && asset.kind === mediaKind && asset.role !== "derivative");
 return <div ref={pickerRef} className="h3-asset-picker" role="group" aria-label={`Project ${mediaKind} inputs`} tabIndex={-1}>{images.map(asset => {
  const name = String(asset.metadata.display_name ?? asset.metadata.original_filename ?? "Image");
  return <button key={asset.id} type="button" title={name} aria-label={name} onClick={() => onChoose(asset)}>{mediaKind === "video" ? <video src={api.assetContentUrl(asset.id)} muted playsInline preload="metadata" aria-label={name} /> : <img src={api.assetContentUrl(asset.id)} loading="lazy" alt={name} />}<span>{name}</span></button>;
 })}{!images.length ? <p>Add {mediaKind === "image" ? "an image" : "a video"} to this project&apos;s library first.</p> : null}</div>;
}
