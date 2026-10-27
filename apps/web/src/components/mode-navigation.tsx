"use client";

import { motion } from "motion/react";
import { Clapperboard, House, MessagesSquare, Network, Scissors } from "lucide-react";
import { rememberAppUrl } from "@/lib/os-navigation";
import { useDariusStore } from "@/lib/store";
import type { ViewId } from "@/lib/types";

const items: { id: ViewId; label: string; icon: typeof MessagesSquare }[] = [
  { id: "home", label: "Home", icon: House },
  { id: "talk", label: "Talk", icon: MessagesSquare },
  { id: "create", label: "Create", icon: Clapperboard },
  { id: "map", label: "Map", icon: Network },
  { id: "edit", label: "Edit", icon: Scissors },
];

export function ModeNavigation({ onNavigate }: { onNavigate?: () => void }) {
  const { view, activeProjectId, setView } = useDariusStore();
  return (
    <nav aria-label="Creative spaces" className="mode-nav app-dock">
      {items.map(({ id, label, icon: Icon }) => (
        <button aria-current={view === id ? "page" : undefined} className={view === id ? "active" : ""} key={id} onClick={() => { rememberAppUrl(id, activeProjectId, "push"); setView(id); onNavigate?.(); }} type="button">
          {view === id ? <motion.span aria-hidden="true" className="dock-active" layoutId="dock-active" /> : null}
          <Icon size={16} aria-hidden="true" /><span>{label}</span>
        </button>
      ))}
    </nav>
  );
}
