"use client";
import { readinessItems, type ReadinessItem } from "@/lib/readiness";
import type { Health } from "@/lib/types";
import type { BoardSetup, ComfyConnection } from "@/lib/board-setup";
export function ReadinessSummary({ health, setup, connection, onAction }: { health?: Health | null; setup?: BoardSetup | null; connection?: ComfyConnection | null; onAction: (action: NonNullable<ReadinessItem["action"]>) => void }) {
 return <section className="readiness-summary" aria-label="Workspace readiness"><h3>Ready to create</h3><p>Board generation needs Darius, ComfyUI and the selected board&apos;s dependencies.</p><dl>{readinessItems(health, setup, connection).map(item => <div key={item.name}><dt>{item.name}<strong>{item.state}</strong></dt><dd>{item.hint}{item.action ? <button type="button" className="text-button" onClick={() => onAction(item.action!)}>{item.action === "connection" ? "Check connection" : item.action === "dependencies" ? "Review dependencies" : "Open settings"}</button> : null}</dd></div>)}</dl></section>;
}
