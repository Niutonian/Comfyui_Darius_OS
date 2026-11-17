"use client";
import { AlignCenterHorizontal, AlignCenterVertical, AlignHorizontalJustifyStart, AlignHorizontalSpaceAround, AlignVerticalJustifyStart, AlignVerticalSpaceAround, Frame, Sparkles, X } from "lucide-react";

/** Appears when several boards are selected: arrange, frame, or generate them together. */
export function SelectionBar({ count, canGenerate, onAlign, onDistribute, onFrame, onGenerate, onClear }: {
  count: number; canGenerate: number;
  onAlign: (edge: "left" | "top" | "centre-x" | "centre-y") => void; onDistribute: (axis: "x" | "y") => void;
  onFrame: () => void; onGenerate: () => void; onClear: () => void;
}) {
  return <div className="dk-selection-bar" role="toolbar" aria-label={`${count} boards selected`}>
    <strong>{count} boards</strong>
    <i aria-hidden="true" />
    <button type="button" aria-label="Align left edges" title="Align left edges" onClick={() => onAlign("left")}><AlignHorizontalJustifyStart size={16} /></button>
    <button type="button" aria-label="Align top edges" title="Align top edges" onClick={() => onAlign("top")}><AlignVerticalJustifyStart size={16} /></button>
    <button type="button" aria-label="Centre in a column" title="Centre in a column" onClick={() => onAlign("centre-x")}><AlignCenterVertical size={16} /></button>
    <button type="button" aria-label="Centre in a row" title="Centre in a row" onClick={() => onAlign("centre-y")}><AlignCenterHorizontal size={16} /></button>
    <button type="button" aria-label="Distribute horizontally" title="Even gaps across" disabled={count < 3} onClick={() => onDistribute("x")}><AlignHorizontalSpaceAround size={16} /></button>
    <button type="button" aria-label="Distribute vertically" title="Even gaps down" disabled={count < 3} onClick={() => onDistribute("y")}><AlignVerticalSpaceAround size={16} /></button>
    <i aria-hidden="true" />
    <button type="button" className="dk-selection-text" onClick={onFrame}><Frame size={15} />Frame</button>
    <button type="button" className="dk-selection-text is-primary" disabled={!canGenerate} onClick={onGenerate}><Sparkles size={15} />Generate {canGenerate}</button>
    <button type="button" aria-label="Clear selection" title="Clear selection (Esc)" onClick={onClear}><X size={16} /></button>
  </div>;
}
