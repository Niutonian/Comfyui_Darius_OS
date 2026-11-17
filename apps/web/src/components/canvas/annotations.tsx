"use client";
import type { CSSProperties } from "react";
import { Trash2 } from "lucide-react";
import type { Annotation } from "@/lib/moss-workspace";

export const noteColors: Annotation["color"][] = ["sun", "moss", "sky", "rose", "stone"];
const colorNames: Record<Annotation["color"], string> = { sun: "Sun", moss: "Moss", sky: "Sky", rose: "Rose", stone: "Stone" };

/**
 * Sticky notes and frames live in canvas (world) units, like boards. Dragging and
 * resizing are handled by the canvas stage through `data-note-id` and
 * `data-note-handle`; this only renders and edits text and colour.
 */
export function CanvasAnnotation({ note, selected, scale, onSelect, onText, onColor, onDelete }: {
  note: Annotation; selected: boolean; scale: number;
  onSelect: () => void; onText: (text: string) => void; onColor: (color: Annotation["color"]) => void; onDelete: () => void;
}) {
  const style = { left: note.x, top: note.y, width: note.width, height: note.height, "--note-label-scale": 1 / scale } as CSSProperties;
  const tools = selected ? <div className="cv-note-tools" role="toolbar" aria-label={`${note.kind === "frame" ? "Frame" : "Note"} options`} onPointerDown={event => event.stopPropagation()}>
    {noteColors.map(color => <button key={color} type="button" className={`cv-swatch tone-${color}`} aria-label={`${colorNames[color]} colour`} aria-pressed={note.color === color} onClick={() => onColor(color)} />)}
    <i aria-hidden="true" />
    <button type="button" className="cv-note-delete" aria-label={`Delete ${note.kind}`} onClick={onDelete}><Trash2 size={14} /></button>
  </div> : null;
  if (note.kind === "frame") return <div className={`cv-frame tone-${note.color} ${selected ? "is-selected" : ""}`} data-note-id={note.id} style={style} aria-label={`Frame ${note.text || "untitled"}`} role="group">
    <div className="cv-frame-title" data-note-handle="move" onPointerDown={onSelect}>
      {selected ? <input aria-label="Frame title" defaultValue={note.text} key={note.text} placeholder="Name this frame" maxLength={200} onPointerDown={event => event.stopPropagation()} onBlur={event => onText(event.target.value.trim())} onKeyDown={event => { if (event.key === "Enter") event.currentTarget.blur(); }} />
        : <span>{note.text || "Untitled frame"}</span>}
    </div>
    {tools}
    {selected ? <span className="cv-resize" data-note-handle="resize" aria-hidden="true" /> : null}
  </div>;
  return <div className={`cv-note tone-${note.color} ${selected ? "is-selected" : ""}`} data-note-id={note.id} style={style} role="note" aria-label={note.text ? `Note: ${note.text.slice(0, 80)}` : "Empty note"} onPointerDown={onSelect}>
    <div className="cv-note-grip" data-note-handle="move" aria-hidden="true" />
    {selected ? <textarea aria-label="Note text" defaultValue={note.text} key={note.text} placeholder="Write a note…" maxLength={2000} onPointerDown={event => event.stopPropagation()} onBlur={event => onText(event.target.value)} />
      : <p>{note.text || "Click to write"}</p>}
    {tools}
    {selected ? <span className="cv-resize" data-note-handle="resize" aria-hidden="true" /> : null}
  </div>;
}
