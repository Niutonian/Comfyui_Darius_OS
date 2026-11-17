"use client";
import type { AppId } from "@/lib/desktop-apps";
import { ASSET_MIME } from "@/lib/canvas-drop";
import { useDariusStore } from "@/lib/store";
import type { Asset, Workflow } from "@/lib/types";
import { CreativeIdeas } from "../creative-ideas";
import { ProductionStructure } from "../production-structure";
import { ShotProductionBoard } from "../shot-production-board";
import { CloudGeneration } from "../cloud-generation";
import { TrustedWorkflows } from "../trusted-workflows";
import { MapView } from "../map-view";
import { EditView } from "../edit-view";
import { SettingsView } from "../settings-view";
import { LibraryApp } from "../library-app";
import { EmptyState } from "../states";

export type AppContext = {
  projectId: string | null; assets: Asset[]; assetsLoading: boolean; assetsError: boolean; workflows: Workflow[];
  openApp: (app: AppId) => void;
};

/** What each window shows. Every app keeps its own scrolling inside the window body.
 *  `onConversationHost`/`onComposerHost` receive the chat window's slots for the shell-owned conversation. */
export function AppContent({ app, context, onConversationHost, onComposerHost }: { app: AppId; context: AppContext; onConversationHost: (node: HTMLDivElement | null) => void; onComposerHost: (node: HTMLDivElement | null) => void }) {
  const { projectId, assets } = context;
  if (app === "settings") return <SettingsView key={`settings:${projectId}`} />;
  // Images dragged from the Library or the canvas become references for the next message.
  if (app === "chat") return <div className="dk-chat" onDragOver={event => { if (event.dataTransfer.types.includes(ASSET_MIME)) { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; } }}
    onDrop={event => { const id = event.dataTransfer.getData(ASSET_MIME); if (!id) return; event.preventDefault(); if (assets.find(asset => asset.id === id)?.kind === "image") useDariusStore.getState().addReferenceAsset(id); }}>
    <div className="dk-chat-conversation" ref={onConversationHost} /><div className="dk-chat-composer" ref={onComposerHost} /></div>;
  if (!projectId) return <EmptyState title="Choose a project" description="Open a project from the launcher to use this app." />;
  if (app === "library") return <LibraryApp assets={assets} isLoading={context.assetsLoading} hasError={context.assetsError} />;
  if (app === "map") return <MapView key={`map:${projectId}`} assets={assets} workflows={context.workflows} onOrganizeStory={() => context.openApp("characters")} />;
  if (app === "edit") return <EditView key={`edit:${projectId}`} assets={assets} assistantOpen={false} onToggleAssistant={() => context.openApp("chat")} onAssistantHost={() => {}} onComposerHost={() => {}} />;
  const body = app === "ideas" ? <CreativeIdeas key={projectId} projectId={projectId} />
    : app === "characters" || app === "scenes" ? <ProductionStructure assets={assets} focus={app} projectId={projectId} />
    : app === "shots" ? <ShotProductionBoard key={projectId} projectId={projectId} assets={assets} />
    : app === "cloud" ? <CloudGeneration key={projectId} projectId={projectId} assets={assets} />
    : <TrustedWorkflows key={projectId} projectId={projectId} />;
  return <div className="dk-app-scroll">{body}</div>;
}
