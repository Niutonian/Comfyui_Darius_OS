"use client";
import { useId, type ReactNode } from "react";
import { History, Layers3, X } from "lucide-react";

/** The selected board's settings and versions, shown in the desktop's right column. */
export function BoardPanel({ name, tab, onTab, onClose, board, history }: {
  name: string; tab: "board" | "history"; onTab: (tab: "board" | "history") => void; onClose: () => void; board: ReactNode; history: ReactNode;
}) {
  const id = useId();
  const tabs = [["board", "Board", Layers3], ["history", "History", History]] as const;
  return <section className="dk-board-panel" aria-label={`Board ${name}`}>
    <header>
      <div role="tablist" aria-label="Board views">{tabs.map(([key, label, Icon]) => <button key={key} type="button" role="tab" id={`${id}-${key}`} aria-selected={tab === key} aria-controls={`${id}-${key}-panel`} onClick={() => onTab(key)}><Icon size={14} />{label}</button>)}</div>
      <button type="button" className="icon-button" aria-label="Close board panel" onClick={onClose}><X size={15} /></button>
    </header>
    <div className="dk-board-panel-body" role="tabpanel" id={`${id}-${tab}-panel`} aria-labelledby={`${id}-${tab}`}>{tab === "board" ? board : history}</div>
  </section>;
}
