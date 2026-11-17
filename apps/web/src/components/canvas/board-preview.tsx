"use client";
/* eslint-disable @next/next/no-img-element -- immutable local preview derivatives */
import { useQuery } from "@tanstack/react-query";
import { api, request } from "@/lib/api-client";
import type { MossBoard } from "@/lib/moss-workspace";
import type { Asset } from "@/lib/types";
import { ImageRecipeInputPreview, isImageRecipeBoard } from "../image-recipe-board";
import { VideoCardPreview, isVideoBoard } from "../video-board";

/** One cached thumbnail derivative per immutable asset. */
export function useThumbnail(assetId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ["moss-thumbnail", assetId], enabled: Boolean(assetId) && enabled, staleTime: Infinity, retry: 1,
    queryFn: async () => (await request<{ derivatives: Asset[] }>(`/assets/${encodeURIComponent(assetId!)}/derivatives?thumbnail_only=true`, { method: "POST" })).derivatives.find(a => a.metadata.derivative_type === "thumbnail")?.id,
  });
}

export function BoardPreview({ board, large = false }: { board: MossBoard; large?: boolean }) {
  const asset = board.activeResult?.assetIds[0];
  const thumbnail = useThumbnail(asset, !board.previewAssetId);
  const image = board.previewAssetId ?? thumbnail.data;
  if (isImageRecipeBoard(board) && !board.activeResult) return <ImageRecipeInputPreview board={board} />;
  if (isVideoBoard(board)) return <VideoCardPreview board={board} />;
  return <div className={`moss-preview ${large ? "large" : ""}`}>
    {image ? <><img className="moss-image-backdrop" src={api.assetContentUrl(image)} alt="" aria-hidden="true" loading="lazy" draggable={false} /><img className="moss-image-artwork" src={api.assetContentUrl(image)} alt={`${board.name} · selected result`} loading="lazy" draggable={false} /></>
      : <svg role="img" aria-label={`${board.name} layout preview`} viewBox={`0 0 ${board.artboard.width} ${board.artboard.height}`}><rect width="100%" height="100%" fill="#f8f4e9" />{board.layout.map(r => <rect key={r.id} x={r.rect[0]} y={r.rect[1]} width={r.rect[2]} height={r.rect[3]} fill="none" stroke={r.kind === "text" ? "#bc8f59" : "#819c83"} strokeWidth={5} strokeDasharray={r.kind === "group" ? "16 10" : undefined} />)}</svg>}
    {!asset && !board.layout.length ? <span>Space for an idea</span> : null}
    {asset && !image ? <span>Preparing thumbnail…</span> : null}
  </div>;
}

export function VisualNoteThumbnail({ assetId }: { assetId: string }) {
  const thumbnail = useThumbnail(assetId);
  return thumbnail.data ? <img className="moss-note-thumbnail" alt="Pinned immutable visual note — not sent to MOSS" src={api.assetContentUrl(thumbnail.data)} loading="lazy" /> : <small>{thumbnail.isLoading ? "Loading pinned version…" : "Reference preview unavailable"}</small>;
}
