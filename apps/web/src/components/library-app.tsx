"use client";
import { ArrowUpRight, Layers3, LayoutGrid, MoreHorizontal, Search, Trash2, X } from "lucide-react";
import { useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useWorkspaceScroll, useWorkspaceState } from "@/lib/workspace-session";
import { useDariusStore } from "@/lib/store";
import { api } from "@/lib/api-client";
import { queryKeys, useCharacters, useScenes } from "@/lib/queries";
import type { Asset, Character, Scene } from "@/lib/types";
import { formatDate, titleCase } from "@/lib/utils";
import { assetName } from "@/lib/chat-labels";
import { EmptyState, LoadingState } from "./states";
import { AssetPreview } from "./asset-preview";
import { LocalRenderSetting } from "./local-render-setting";

type LibraryLayout = "table" | "stacks";
type GroupBy = "kind" | "scene" | "role" | "character";
/** Library assets can be dragged onto the canvas, a board or the chat. */
export const ASSET_MIME = "application/x-darius-asset";

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

function sendToDarius(asset: Asset) {
  useDariusStore.getState().addReferenceAsset(asset.id);
  useDariusStore.getState().setView("talk");
}

function AssetCard({ asset, index, navigationAssets, onInspect, onFeature, onDelete }: { asset: Asset; index: number; navigationAssets: Asset[]; onInspect: () => void; onFeature: () => void; onDelete: () => void }) {
  return (
    <article className="asset-card os-enter" style={{ animationDelay: `${Math.min(index, 12) * 45}ms` }} draggable onDragStart={event => { event.dataTransfer.setData(ASSET_MIME, asset.id); event.dataTransfer.effectAllowed = "copy"; }}>
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
        {asset.kind === "image" ? <button className="secondary-button" type="button" onClick={() => sendToDarius(asset)}>Use with Darius <ArrowUpRight size={13} /></button> : null}
        {(asset.kind === "image" || asset.kind === "video") ? <button aria-label={`Delete ${asset.kind}`} className="icon-button danger-icon" onClick={onDelete} title={`Delete ${asset.kind}`} type="button"><Trash2 size={14} /></button> : null}
        <small title="Asset ID">ID · {asset.id.slice(0, 8)}</small>
      </div></details>
    </article>
  );
}

/** The project's generated and imported media. Opens as a window over the canvas. */
export function LibraryApp({ assets: allAssets, isLoading, hasError }: { assets: Asset[]; isLoading: boolean; hasError: boolean }) {
  // Preview derivatives remain addressable internally, but are not library items.
  const assets = useMemo(() => allAssets.filter(asset => asset.role !== "derivative"), [allAssets]);
  const { activeProjectId, setSelection } = useDariusStore();
  const scope = `library:${activeProjectId}`;
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
  const card = (asset: Asset, index: number, onFeature: () => void) => <AssetCard asset={asset} index={index} key={asset.id} navigationAssets={filtered} onDelete={() => void deleteAsset(asset)} onFeature={onFeature} onInspect={() => setSelection({ type: "asset", id: asset.id })} />;

  return <section ref={scroll} className="library-desk library-app" aria-label="Project library">
    <div className="library-app-head">
      <span className="library-stats"><b>{counts.image}</b> images <b>{counts.video}</b> video <b>{counts.audio}</b> audio</span>
      <div className="segmented" aria-label="Library layout">
        <button aria-pressed={layout === "table"} className={layout === "table" ? "active" : ""} onClick={() => setLayout("table")} type="button"><LayoutGrid size={14} /> Light table</button>
        <button aria-pressed={layout === "stacks"} className={layout === "stacks" ? "active" : ""} onClick={() => setLayout("stacks")} type="button"><Layers3 size={14} /> Stacks</button>
      </div>
    </div>
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
    {activeProjectId && !isLoading && !hasError && !assets.length ? <EmptyState title="Your library is ready" description="Generate on a board, or drop files onto the canvas, to start your collection." /> : null}
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
            {featured.kind === "image" ? <button className="secondary-button" type="button" onClick={() => sendToDarius(featured)}>Use with Darius <ArrowUpRight size={13} /></button> : null}
          </div>
        </div>
      </article> : null}
      <section aria-label="Project assets" className="asset-grid create-bento">{rest.map((asset, index) => card(asset, index, () => setFeaturedId(asset.id)))}</section>
    </div> : null}
    {filtered.length > 0 && layout === "stacks" ? <div className="library-stacks" aria-label="Stacked library">
      {groups.map((group) => <section className="library-stack os-enter" key={group.label}>
        <header><strong>{group.label}</strong><span>{group.items.length}</span></header>
        <div className="library-stack-pile">{group.items.map((asset, index) => card(asset, index, () => { setFeaturedId(asset.id); setLayout("table"); }))}</div>
      </section>)}
    </div> : null}
  </section>;
}
