"use client";

import { FileAudio2, FileImage, FileVideo2 } from "lucide-react";
import { api } from "@/lib/api-client";
import type { Asset } from "@/lib/types";
import { assetName } from "@/lib/chat-labels";

export function MediaPreview({ asset, compact = false }: { asset: Asset; compact?: boolean }) {
  const url = api.assetContentUrl(asset.id);
  const label = `${asset.kind} preview for ${assetName(asset)}`;
  // Native media elements support local/object URLs and backend URLs not known at build time.
  // eslint-disable-next-line @next/next/no-img-element
  if (url && asset.kind === "image") return <img alt={label} className="media-preview" src={url} loading="lazy" />;
  if (url && asset.kind === "video") return <video aria-label={label} className="media-preview" controls={!compact} muted={compact} preload="metadata" src={url} />;
  if (url && asset.kind === "audio" && !compact) return <audio aria-label={label} className="audio-preview" controls preload="metadata" src={url} />;
  const Icon = asset.kind === "image" ? FileImage : asset.kind === "audio" ? FileAudio2 : FileVideo2;
  return <span className="preview-placeholder"><Icon aria-hidden size={compact ? 28 : 36} /><span>{asset.kind}</span>{compact ? null : <small>Preview stream unavailable</small>}</span>;
}
