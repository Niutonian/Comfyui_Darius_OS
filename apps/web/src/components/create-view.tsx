"use client";
import { CreativeIdeas } from "./creative-ideas";

import { ArrowUpRight, Clapperboard, Layers3, LayoutGrid, Library, MapPin, MoreHorizontal, Scan, Search, SlidersHorizontal, Trash2, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { useWorkspaceScroll, useWorkspaceState } from "@/lib/workspace-session";
import { useQueryClient } from "@tanstack/react-query";
import { useDariusStore } from "@/lib/store";
import { api } from "@/lib/api-client";
import { queryKeys, useCharacters, useScenes } from "@/lib/queries";
import type { Asset, Character, Scene } from "@/lib/types";
import { formatDate, titleCase } from "@/lib/utils";
import { EmptyState, LoadingState } from "./states";
import { AssetPreview } from "./asset-preview";
import { ProductionStructure } from "./production-structure";
import { ShotProductionBoard } from "./shot-production-board";
import { TrustedWorkflows } from "./trusted-workflows";
import { LocalRenderSetting } from "./local-render-setting";
import { CloudGeneration } from "./cloud-generation";
import { assetName } from "@/lib/chat-labels";
import { MossWorkspace } from "./moss-workspace";

type LibraryLayout = "table" | "stacks";

type GroupBy = "kind" | "scene" | "role" | "character";

export function groupLibrary(assets: Asset[], characters: Character[], scenes: Scene[], groupBy: GroupBy) {
  const sceneName = (id: string | null) => scenes.find((scene) => scene.id === id)?.title ?? "Unplaced";
  const characterName = (assetId: string) => characters.find((character) => character.approved_reference_asset_ids.includes(assetId))?.name ?? "Unassigned";
  const keyFor = (asset: Asset) => {
    if (groupBy === "kind") return titleCase(asset.kind);
    if (groupBy === "role") return titleCase(asset.role);
    if (groupBy === "scene") return sceneName(asset.scene_id);
    return characterName(asset.id);
  };
  const groups = new Map<string, Asset[]>();
  assets.forEach((asset) => {
    const key = keyFor(asset);
    groups.set(key, [...(groups.get(key) ?? []), asset]);
  });
  return [...groups.entries()].map(([label, items]) => ({ label, items }));
}

function AssetCard({ asset, index, navigationAssets, onInspect, onFeature, onDelete }: { asset: Asset; index: number; navigationAssets: Asset[]; onInspect: () => void; onFeature: () => void; onDelete: () => void }) {
  return (
    <article className="asset-card os-enter" style={{ animationDelay: `${Math.min(index, 12) * 45}ms` }}>
      <span className={`asset-visual kind-${asset.kind}`}>
        <AssetPreview asset={asset} compact navigationAssets={navigationAssets} />
        <span>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : titleCase(asset.kind)}</span>
      </span>
      <button aria-label={`Inspect ${assetName(asset)}`} className="asset-body asset-details-button" onClick={onInspect} type="button">
        <span><small>{titleCase(asset.role)}</small><strong title={assetName(asset)}>{assetName(asset)}</strong></span>
        <em>{formatDate(asset.created_at)}</em>
      </button>
      <span className="asset-tags"><i>{titleCase(asset.approval_state)}</i>{asset.duration ? <i>{asset.duration.toFixed(1)}s</i> : null}</span>
      <details className="asset-card-overflow"><summary aria-label={`Actions for ${assetName(asset)}`}><MoreHorizontal size={18} /><span>Actions</span></summary><div className="asset-card-actions">
        <button className="text-button" type="button" onClick={onFeature}>Pin to project</button>
        {asset.kind === "image" ? <button className="secondary-button" type="button" onClick={() => { useDariusStore.getState().addReferenceAsset(asset.id); useDariusStore.getState().setView("talk"); }}>Use with Darius <ArrowUpRight size={13} /></button> : null}
        {(asset.kind === "image" || asset.kind === "video") ? <button aria-label={`Delete ${asset.kind}`} className="icon-button danger-icon" onClick={onDelete} title={`Delete ${asset.kind}`} type="button"><Trash2 size={14} /></button> : null}
        <small title="Asset ID">ID · {asset.id.slice(0, 8)}</small>
      </div></details>
    </article>
  );
}

export function CreateView({ assets: allAssets, isLoading, hasError, initialStoryOpen = false, onCanvasComposerHost, onCanvasAssistantHost, canvasAssistantOpen, onToggleCanvasAssistant, onCanvasBoardContext }: {
  assets: Asset[]; isLoading: boolean; hasError: boolean; initialStoryOpen?: boolean;
  onCanvasComposerHost?: (host: HTMLDivElement | null) => void; onCanvasAssistantHost?: (host: HTMLDivElement | null) => void;
  canvasAssistantOpen?: boolean; onToggleCanvasAssistant?: () => void; onCanvasBoardContext?: (context: import("@/lib/moss-workspace").SelectedBoardContext | null) => void;
}) {
  // Preview derivatives remain addressable internally, but are not library items.
  const assets = useMemo(() => allAssets.filter(asset => asset.role !== "derivative"), [allAssets]);
  const { activeProjectId, setSelection, setTrayOpen } = useDariusStore();
  const scope = `create:${activeProjectId}`;
  const [section, setSection] = useWorkspaceState<"library" | "ideas" | "canvas" | "characters" | "scenes" | "shots" | "cloud" | "workflows">(`${scope}:section`, initialStoryOpen ? "characters" : "library");
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get("project") === activeProjectId && (params.has("board") || params.has("canvas"))) setSection("canvas");
  }, [activeProjectId, setSection]);
  const [canvasExpanded, setCanvasExpanded] = useWorkspaceState(`${scope}:canvas-expanded`, true);
  const scroll = useRef<HTMLDivElement>(null);
  useWorkspaceScroll(`${scope}:scroll`, scroll);
  const characters = useCharacters(activeProjectId);
  const scenes = useScenes(activeProjectId);
  const [kind, setKind] = useWorkspaceState(`${scope}:kind`, "all");
  const [sort, setSort] = useWorkspaceState(`${scope}:sort`, "newest");
  const [query, setQuery] = useWorkspaceState(`${scope}:query`, "");
  const [layout, setLayout] = useWorkspaceState<LibraryLayout>(`${scope}:layout`, "table");
  const [groupBy, setGroupBy] = useWorkspaceState<GroupBy>(`${scope}:group`, "kind");
  const [featuredId, setFeaturedId] = useWorkspaceState<string | null>(`${scope}:pin`, null);
  const client = useQueryClient();
  async function deleteAsset(asset: Asset) {
    if (!window.confirm(`Delete this ${asset.kind}? This cannot be undone.`)) return;
    await api.deleteAsset(asset.id);
    if (featuredId === asset.id) setFeaturedId(null);
    await client.invalidateQueries({ queryKey: queryKeys.projectAssets(activeProjectId ?? "none") });
  }
  const filtered = useMemo(() => assets.filter((asset) =>
    (kind === "all" || asset.kind === kind) &&
    (asset.id.toLowerCase().includes(query.toLowerCase()) || asset.provider.toLowerCase().includes(query.toLowerCase()) || assetName(asset).toLowerCase().includes(query.toLowerCase().trim())),
  ).sort((a, b) => sort === "name" ? assetName(a).localeCompare(assetName(b)) : sort === "oldest" ? a.created_at.localeCompare(b.created_at) : b.created_at.localeCompare(a.created_at)), [assets, kind, query, sort]);
  const featured = filtered.find((asset) => asset.id === featuredId);
  const rest = filtered.filter((asset) => asset.id !== featured?.id);
  const groups = useMemo(() => groupLibrary(filtered, characters.data ?? [], scenes.data ?? [], groupBy), [filtered, characters.data, scenes.data, groupBy]);
  const counts = {
    image: assets.filter((asset) => asset.kind === "image").length,
    video: assets.filter((asset) => asset.kind === "video").length,
    audio: assets.filter((asset) => asset.kind === "audio").length,
  };

  return (
    <div ref={scroll} className={`view create-view ${section === "canvas" ? `is-canvas ${canvasExpanded ? "is-expanded" : ""}` : ""}`}>
      <header className="view-heading"><div><span className="eyebrow">Your creative library</span><h1>Create & review</h1><p>Find your next shot. Browse, compare, and build on what you have created.</p></div><div className="create-heading-actions"><button className="primary-button" disabled={!activeProjectId} onClick={() => useDariusStore.getState().setView("talk")} type="button">Create with Darius <ArrowUpRight size={15} /></button><button className="secondary-button" onClick={() => setTrayOpen(true)} type="button"><SlidersHorizontal size={16} /> Review queue</button></div></header>
      <div className="create-shell">
      <nav className="create-rail" aria-label="Library sections">
        {([
          ["library", "Library", <Library size={15} key="library" />, assets.length],
          ["ideas", "Ideas", <Layers3 size={15} key="ideas" />, null],
          ["canvas", "Canvas", <Scan size={15} key="canvas" />, null],
          ["characters", "Characters", <UserRound size={15} key="characters" />, characters.data?.length ?? 0],
          ["scenes", "Scenes", <MapPin size={15} key="scenes" />, scenes.data?.length ?? 0],
          ["shots", "Shots", <Clapperboard size={15} key="shots" />, null],
          ["cloud", "Cloud / FLUX 3", <SlidersHorizontal size={15} key="cloud" />, null],
          ["workflows", "Trusted workflows", <Layers3 size={15} key="workflows" />, null],
        ] as const).map(([id, label, icon, count]) => <button aria-current={section === id ? "page" : undefined} key={id} onClick={() => setSection(id)} type="button"><span>{icon} {label}</span>{count !== null ? <span>{count}</span> : null}</button>)}
      </nav>
      <div className="create-main">
      {section === "ideas" && activeProjectId ? <CreativeIdeas key={activeProjectId} projectId={activeProjectId}/> : section === "canvas" && activeProjectId ? <MossWorkspace projectId={activeProjectId} assets={allAssets} expanded={canvasExpanded} onToggleExpanded={() => setCanvasExpanded(value => !value)} onExitWorkspace={() => setSection("library")} onComposerHost={onCanvasComposerHost} onAssistantHost={onCanvasAssistantHost} assistantOpen={canvasAssistantOpen} onToggleAssistant={onToggleCanvasAssistant} onBoardContext={onCanvasBoardContext} /> : section === "workflows" && activeProjectId ? <TrustedWorkflows key={activeProjectId} projectId={activeProjectId} /> : section === "cloud" && activeProjectId ? <CloudGeneration key={activeProjectId} projectId={activeProjectId} assets={allAssets} /> : section === "shots" && activeProjectId ? <ShotProductionBoard key={activeProjectId} projectId={activeProjectId} assets={allAssets} /> : (section === "characters" || section === "scenes") && activeProjectId ? <ProductionStructure assets={allAssets} focus={section} projectId={activeProjectId} /> : null}
      {section === "library" ? <section className="library-desk os-window" aria-label="Project library">
        <header className="os-chrome">
          <span className="os-chrome-dots" aria-hidden="true"><i /><i /><i /></span>
          <strong>Library</strong>
          <span className="library-stats"><b>{counts.image}</b> images <b>{counts.video}</b> video <b>{counts.audio}</b> audio</span>
          <div className="segmented" aria-label="Library layout">
            <button aria-pressed={layout === "table"} className={layout === "table" ? "active" : ""} onClick={() => setLayout("table")} type="button"><LayoutGrid size={14} /> Light table</button>
            <button aria-pressed={layout === "stacks"} className={layout === "stacks" ? "active" : ""} onClick={() => setLayout("stacks")} type="button"><Layers3 size={14} /> Stacks</button>
          </div>
        </header>
        <div className="asset-toolbar">
          <label className="search-field"><Search size={16} /><span className="sr-only">Search assets</span><input onChange={(event) => setQuery(event.target.value)} placeholder="Search your library…" value={query} />{query ? <button className="icon-button" aria-label="Clear asset search" onClick={() => setQuery("")} type="button"><X size={14} /></button> : null}</label>
          <label className="filter-field"><span className="sr-only">Sort assets</span><select value={sort} onChange={(event) => setSort(event.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="name">Name A–Z</option></select></label>
          {layout === "stacks" ? <label className="filter-field"><Layers3 size={15} /><span className="sr-only">Stack by</span><select onChange={(event) => setGroupBy(event.target.value as GroupBy)} value={groupBy}><option value="kind">By kind</option><option value="role">By role</option><option value="scene">By scene</option><option value="character">By character</option></select></label> : null}
          <span className="asset-count">{filtered.length} {filtered.length === 1 ? "asset" : "assets"}</span>
          {activeProjectId ? <div className="generation-route"><LocalRenderSetting compact projectId={activeProjectId} /><span>Cloud and custom graphs still ask first.</span></div> : null}
        </div>
        <div className="library-media-tabs" aria-label="Media types">{(["all", "image", "video", "audio"] as const).map((type) => <button key={type} type="button" aria-pressed={kind === type} onClick={() => setKind(type)}>{type === "all" ? "All media" : type === "image" ? "Images" : type === "video" ? "Videos" : "Audio"}<span>{type === "all" ? assets.length : counts[type]}</span></button>)}{kind !== "all" || query ? <button className="library-reset" onClick={() => { setKind("all"); setQuery(""); }} type="button">Reset filters</button> : null}</div>
        {!activeProjectId ? <EmptyState title="No active project" description="Choose a project to see its generated assets." /> : null}
        {activeProjectId && isLoading ? <LoadingState label="Loading generated assets…" /> : null}
        {activeProjectId && hasError && !assets.length ? <EmptyState title="Assets are temporarily unavailable" description="Your library could not be loaded. Check the local service and try again." /> : null}
        {activeProjectId && !isLoading && !hasError && !assets.length ? <EmptyState title="Your canvas is ready" description="Create with Darius or attach a file below to start your collection." /> : null}
        {assets.length > 0 && !filtered.length ? <EmptyState title="No matching assets" description="Try a different media type or search term." /> : null}
        {filtered.length > 0 && layout === "table" ? <div className="library-stage">
          {featured ? <article className="library-hero os-enter">
            <div className={`asset-visual kind-${featured.kind}`}><AssetPreview asset={featured} navigationAssets={filtered} /></div>
            <div className="library-hero-copy">
              <div className="library-pin-heading"><span className="eyebrow">Pinned to your desk</span><button className="icon-button" aria-label="Unpin from desk" onClick={() => setFeaturedId(null)} type="button"><X size={16} /></button></div>
              <h2>{assetName(featured)}</h2>
              <p>{titleCase(featured.role)} · {featured.provider} · {formatDate(featured.created_at)}</p>
              <div className="library-hero-actions">
                <button className="primary-button" onClick={() => setSelection({ type: "asset", id: featured.id })} type="button">Inspect</button>
                {featured.kind === "image" ? <button className="secondary-button" type="button" onClick={() => { useDariusStore.getState().addReferenceAsset(featured.id); useDariusStore.getState().setView("talk"); }}>Use with Darius <ArrowUpRight size={13} /></button> : null}
              </div>
            </div>
          </article> : null}
          <section aria-label="Project assets" className="asset-grid create-bento">
            {rest.map((asset, index) => (
              <AssetCard asset={asset} index={index} key={asset.id} navigationAssets={filtered} onDelete={() => void deleteAsset(asset)} onFeature={() => setFeaturedId(asset.id)} onInspect={() => setSelection({ type: "asset", id: asset.id })} />
            ))}
          </section>
        </div> : null}
        {filtered.length > 0 && layout === "stacks" ? <div className="library-stacks" aria-label="Stacked library">
          {groups.map((group) => (
            <section className="library-stack os-enter" key={group.label}>
              <header><strong>{group.label}</strong><span>{group.items.length}</span></header>
              <div className="library-stack-pile">
                {group.items.map((asset, index) => (
                <AssetCard asset={asset} index={index} key={asset.id} navigationAssets={filtered} onDelete={() => void deleteAsset(asset)} onFeature={() => { setFeaturedId(asset.id); setLayout("table"); }} onInspect={() => setSelection({ type: "asset", id: asset.id })} />
                ))}
              </div>
            </section>
          ))}
        </div> : null}
      </section> : null}
      </div>
      </div>
    </div>
  );
}
