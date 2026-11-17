"use client";
/* eslint-disable @next/next/no-img-element -- local project media */
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, MessageCircle, PanelRightClose, PanelRightOpen } from "lucide-react";
import type { ReactNode } from "react";
import { api } from "@/lib/api-client";
import { ideasApi } from "@/lib/creative-ideas";
import { useCharacters } from "@/lib/queries";
import type { AppId } from "@/lib/desktop-apps";
import type { Asset, DariusMood, Job } from "@/lib/types";
import { LiquidOrb } from "../liquid-orb";
import { DotWord } from "./dot-word";
import { CharactersIcon, IdeasIcon, LibraryIcon, QueueIcon } from "./icons";

function Tile({ label, icon, count, alert, onOpen, children }: { label: string; icon: ReactNode; count?: number; alert?: boolean; onOpen: () => void; children: ReactNode }) {
  return <button type="button" className="dk-tile" onClick={onOpen} aria-label={`${label}${count !== undefined ? ` · ${count}` : ""}`}>
    <header><span>{icon}{label}</span>{count !== undefined ? <b className={alert ? "is-alert" : ""}>{count}</b> : <ArrowRight size={14} />}</header>
    <div className="dk-tile-body">{children}</div>
  </button>;
}

/**
 * Always-present Darius: the orb, voice controls and a quick message line. The shell's
 * conversation portals into these slots; voice keeps running whatever window is open.
 */
export function DariusCard({ mood, onVoiceHost, onComposerHost, onOpenChat, chatOpen }: {
  mood: DariusMood; chatOpen: boolean; onVoiceHost: (node: HTMLDivElement | null) => void; onComposerHost: (node: HTMLDivElement | null) => void; onOpenChat: () => void;
}) {
  return <section className={`dk-darius mood-${mood}`} aria-label="Darius">
    <header><DotWord text="Darius" height={18} /><button type="button" className="dk-darius-chat" onClick={onOpenChat} aria-pressed={chatOpen}><MessageCircle size={14} />{chatOpen ? "Chat open" : "Open chat"}</button></header>
    <div className="dk-darius-orb"><LiquidOrb mood={mood} size="thought" /></div>
    <div className="dk-darius-voice" ref={onVoiceHost} />
    <div className="dk-darius-composer" ref={onComposerHost} hidden={chatOpen} />
  </section>;
}

export function WidgetColumn({ projectId, assets, jobs, mood, open, boardSelected, chatOpen, onToggle, onApp, onJobs, onPanelHost, onVoiceHost, onComposerHost }: {
  projectId: string; assets: Asset[]; jobs: Job[]; mood: DariusMood; open: boolean; boardSelected: boolean; chatOpen: boolean;
  onToggle: () => void; onApp: (app: AppId) => void; onJobs: () => void;
  onPanelHost: (node: HTMLDivElement | null) => void; onVoiceHost: (node: HTMLDivElement | null) => void; onComposerHost: (node: HTMLDivElement | null) => void;
}) {
  const ideas = useQuery({ queryKey: ["creative-ideas", projectId, false], queryFn: () => ideasApi.list(projectId, false), staleTime: 15_000 });
  const characters = useCharacters(projectId);
  const media = assets.filter(asset => asset.role !== "derivative");
  const latestImage = media.filter(asset => asset.kind === "image").sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const active = jobs.filter(job => job.status === "running" || job.status === "queued" || job.status === "cancelling");
  const failed = jobs.filter(job => job.status === "failed").length;
  const running = active.find(job => job.status === "running");
  return <aside className={`dk-column ${open ? "" : "is-collapsed"}`} aria-label="Project widgets">
    <button type="button" className="dk-column-toggle icon-button" aria-label={open ? "Hide widgets" : "Show widgets"} aria-expanded={open} onClick={onToggle}>{open ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}</button>
    <div className="dk-column-panel" ref={onPanelHost} hidden={!open || !boardSelected} />
    {open && !boardSelected ? <div className="dk-tiles">
      <Tile label="Queue" icon={<QueueIcon size={15} />} count={active.length} alert={failed > 0} onOpen={onJobs}>
        {running ? <><small>{running.display_name || running.status_message || "Rendering"}</small><span className="dk-meter"><b style={{ width: `${Math.round((running.progress ?? 0) * 100)}%` }} /></span></> : <small>{active.length ? `${active.length} waiting` : failed ? `${failed} need attention` : "Nothing rendering"}</small>}
      </Tile>
      <Tile label="Ideas" icon={<IdeasIcon size={15} />} count={ideas.data?.length} onOpen={() => onApp("ideas")}>
        <small className="dk-tile-quote">{ideas.data?.[0]?.title ?? "Save ideas from chat"}</small>
      </Tile>
      <Tile label="Library" icon={<LibraryIcon size={15} />} count={media.length} onOpen={() => onApp("library")}>
        {latestImage ? <img src={api.assetContentUrl(latestImage.id)} alt="" loading="lazy" /> : <small>Generated media lands here</small>}
      </Tile>
      <Tile label="Characters" icon={<CharactersIcon size={15} />} count={characters.data?.length} onOpen={() => onApp("characters")}>
        <span className="dk-tile-faces">{(characters.data ?? []).slice(0, 4).map(character => <i key={character.id} title={character.name}>{character.name.slice(0, 1)}</i>)}</span>
      </Tile>
    </div> : null}
    <DariusCard mood={mood} chatOpen={chatOpen} onVoiceHost={onVoiceHost} onComposerHost={onComposerHost} onOpenChat={() => onApp("chat")} />
  </aside>;
}
