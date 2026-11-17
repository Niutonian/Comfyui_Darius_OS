"use client";
import type { CSSProperties } from "react";
import { ArrowRight, Copy, Layers3, Maximize, Sparkles } from "lucide-react";
import { canvasProfiles } from "@/lib/canvas-profile";
import type { MossBoard, Placement } from "@/lib/moss-workspace";
import { VideoCardPreview, isVideoBoard } from "../video-board";
import { BoardPreview } from "./board-preview";
import { WindowBoundary } from "../desktop/window-boundary";

export type BoardCardProps = {
  board: MossBoard; placement: Placement; scale: number; visible: boolean;
  selected: boolean; dragging: boolean; busy: boolean; status: string; error: string;
  generateLabel: string; canGenerate: boolean; creating: boolean;
  onSelect: () => void; onDuplicate: () => void; onFitArtwork: () => void; onOpen: () => void; onGenerate: () => void;
};

/** A board as it sits on the desktop. Positioned in world units; the camera scales the world. */
export function BoardCard({ board, placement, scale, visible, selected, dragging, busy, status, error, generateLabel, canGenerate, creating, onSelect, onDuplicate, onFitArtwork, onOpen, onGenerate }: BoardCardProps) {
  const profile = canvasProfiles[board.settings.adapterVersion];
  const classes = ["moss-board", scale < .65 && "is-compact", placement.displayWidth * scale < 160 && "is-tiny", busy && "is-busy", error && "has-error", board.activeResult && "has-result", dragging && "is-dragging", selected && "selected"].filter(Boolean).join(" ");
  return <article className={classes} data-board-id={board.id}
    style={{ left: placement.x, top: placement.y, width: placement.displayWidth, height: placement.displayHeight, zIndex: dragging ? 3 : selected ? 2 : 1, "--board-label-scale": 1 / scale } as CSSProperties}
    title="Drag the image or title to move this board. Double-click to edit." onClick={onSelect}>
    <header><span className="moss-board-mark"><Layers3 size={17} /></span><div><strong>{board.name}</strong><small>{profile.family} · {profile.name}</small></div>
      <span className={`moss-status state-${status.toLowerCase().replaceAll(" ", "-")}`}>{status}</span>
      <button className="icon-button moss-duplicate" aria-label={`Duplicate board ${board.name}`} title="Duplicate this board independently" disabled={creating || board.archived} onClick={e => { e.stopPropagation(); onDuplicate(); }}><Copy size={15} /></button>
      <button className="icon-button moss-fit-artwork" aria-label={`Fit card to artwork for ${board.name}`} title="Fit this card to the image proportions" onClick={e => { e.stopPropagation(); onFitArtwork(); }}><Maximize size={15} /></button>
    </header>
    <WindowBoundary title="Preview" compact>{isVideoBoard(board) ? <VideoCardPreview board={board} visible={visible} /> : visible ? <BoardPreview board={board} /> : <div className="moss-distant">{board.artboard.width} × {board.artboard.height} · {status}</div>}</WindowBoundary>
    {error ? <div className="moss-board-notice" role="status">{error}</div> : null}
    <div className="moss-card-copy"><small>{board.artboard.width} × {board.artboard.height} · {board.regionCount} regions</small><p>{board.prompt || "Open this board to shape your first composition."}</p>
      <small>{board.activeResult ? `${board.jobs.length ? "Previous result" : "Generated from"} r${board.activeResult.revision} · seed ${board.activeResult.seed}` : "No generated result"}{board.activeResult && board.activeResult.revision !== board.documentRevision ? ` · Draft r${board.documentRevision} has newer edits` : ""}{board.newResult ? " · New result in history" : ""}</small>
      {error ? <p className="form-error">{error}</p> : null}</div>
    <footer><small className="moss-card-meta">{board.jobs.length && board.activeResult ? `Previous result r${board.activeResult.revision}` : `${board.artboard.width} × ${board.artboard.height}`}</small>
      <button className="secondary-button" aria-label={`Open board ${board.name}`} disabled={board.archived} onClick={e => { e.stopPropagation(); onOpen(); }}>Open <ArrowRight size={14} /></button>
      <button className="primary-button" aria-label={generateLabel} title={`Generate ${board.name}`} disabled={!canGenerate} onClick={e => { e.stopPropagation(); onGenerate(); }}><Sparkles size={14} /><span>{generateLabel}</span></button></footer>
  </article>;
}

/** Card visibility for lazy previews: within the stage plus a 200px margin. */
export function inView(placement: Placement, camera: { x: number; y: number; scale: number }, size: { width: number; height: number }) {
  return placement.x * camera.scale + camera.x > -placement.displayWidth * camera.scale - 200 && placement.x * camera.scale + camera.x < size.width + 200
    && placement.y * camera.scale + camera.y > -placement.displayHeight * camera.scale - 200 && placement.y * camera.scale + camera.y < size.height + 200;
}
