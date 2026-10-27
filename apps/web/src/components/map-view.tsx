"use client";

import { Background, Controls, Handle, MiniMap, Position, ReactFlow, useEdgesState, useNodesState, type Edge, type Node, type NodeProps, type ReactFlowInstance } from "@xyflow/react";
import { ArrowLeft, ArrowUpRight, Boxes, LayoutGrid, List, ChevronRight, Compass, Focus, Maximize2, Minimize2, Search, X } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useDariusStore } from "@/lib/store";
import { useCharacters, useScenes } from "@/lib/queries";
import type { Asset, MapAltitude, Workflow } from "@/lib/types";
import { arrangeNodes, buildStoryMap, canDive, focusStoryMap, mapAltitudes, type MapDive, type StoryNodeData } from "@/lib/story-map";
import { EmptyState, ErrorState, LoadingState } from "./states";
import { MediaPreview } from "./media-preview";
import { AssetPreview } from "./asset-preview";
import { useMapLayout } from "@/lib/map-layout";
import { readWorkspaceValue, rememberWorkspaceValue, useWorkspaceState } from "@/lib/workspace-session";

const StoryCard = memo(function StoryCard({ data, selected }: NodeProps<Node<StoryNodeData>>) {
  return <article className={`story-card story-${data.kind} ${selected ? "is-selected" : ""}`}>
    <Handle type="target" position={Position.Left} />
    {data.asset ? <div className="story-thumbnail"><MediaPreview asset={data.asset} compact /></div> : null}
    <div className="story-card-copy"><span className="story-kind">{data.kindLabel}</span><strong>{data.label}</strong><p>{data.subtitle}</p><span className="story-card-foot">{data.badge}{canDive(data.kind) ? <span className="story-dive-hint">Enter</span> : <ArrowUpRight size={13} />}</span></div>
    <Handle type="source" position={Position.Right} />
  </article>;
}, (prev, next) => prev.data === next.data && prev.selected === next.selected && prev.dragging === next.dragging);
const nodeTypes = { story: StoryCard };

function layoutSignature(nodes: Node<StoryNodeData>[], edges: Edge[]) {
  return `${nodes.map((node) => `${node.id}:${Math.round(node.position.x)}:${Math.round(node.position.y)}`).join("|")}#${edges.map((edge) => edge.id).join(",")}`;
}

function paintEdge(edge: Edge, selectedId: string | null, dark: boolean): Edge {
  const active = Boolean(selectedId && (edge.source === selectedId || edge.target === selectedId));
  return {
    ...edge,
    style: { stroke: active ? (dark ? "#b8df82" : "#4e733e") : (dark ? "#647c6d" : "#96aa8e"), strokeWidth: active ? 2 : 1.2 },
    labelStyle: { fill: dark ? "#a8b9ad" : "#56694d", fontSize: 10 },
    labelBgStyle: { fill: dark ? "#24312b" : "#ecf1e6", fillOpacity: .95 },
  };
}

function MapCanvas({ viewportKey, nodes, edges, draggable, selectedId, dimKey, theme, onMove, onSelect, onOpen, onClear, onReady }: {
  viewportKey: string;
  nodes: Node<StoryNodeData>[];
  edges: Edge[];
  draggable: boolean;
  selectedId: string | null;
  dimKey: string;
  theme: "light" | "dark";
  onMove: (id: string, point: { x: number; y: number }) => void;
  onSelect: (node: Node<StoryNodeData>) => void;
  onOpen: (node: Node<StoryNodeData>) => void;
  onClear: () => void;
  onReady: (instance: ReactFlowInstance<Node<StoryNodeData>>) => void;
}) {
  const dark = theme === "dark";
  const [viewport] = useState(() => readWorkspaceValue<{ x: number; y: number; zoom: number }>(viewportKey));
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState(nodes);
  const [flowEdges, setFlowEdges] = useEdgesState(edges.map((edge) => paintEdge(edge, selectedId, dark)));
  const signature = layoutSignature(nodes, edges);
  const appearance = `${signature}|${selectedId ?? ""}|${dimKey}|${theme}`;
  const [seen, setSeen] = useState(appearance);
  const dimmed = new Set(dimKey ? dimKey.split(",") : []);
  if (appearance !== seen) {
    setSeen(appearance);
    setFlowNodes(nodes.map((node) => ({ ...node, selected: node.id === selectedId, style: { opacity: dimKey && !dimmed.has(node.id) ? 0.25 : 1 } })));
    setFlowEdges(edges.map((edge) => paintEdge(edge, selectedId, dark)));
  }
  return <ReactFlow<Node<StoryNodeData>> nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} onInit={onReady} onNodesChange={onNodesChange} defaultViewport={viewport} onMoveEnd={(_, next) => rememberWorkspaceValue(viewportKey, next)} fitView={!viewport} fitViewOptions={{ padding: .12, minZoom: .08, maxZoom: 1 }} minZoom={.08} maxZoom={1.8} nodesDraggable={draggable} zoomOnDoubleClick={false} panOnScroll selectNodesOnDrag={false} multiSelectionKeyCode={null} onNodeDragStop={(_, node) => onMove(node.id, node.position)} nodesConnectable={false} onNodeClick={(_, node) => onSelect(node)} onNodeDoubleClick={(_, node) => onOpen(node)} onPaneClick={onClear} proOptions={{ hideAttribution: true }}>
    <Background color={dark ? "#52675d" : "#aab9a2"} gap={24} size={1} /><Controls showInteractive={false} />{flowNodes.length > 6 ? <MiniMap pannable zoomable ariaLabel="Story overview" maskColor={dark ? "#14201ccc" : "#edf2e6cc"} nodeColor={(node) => { const kind = (node.data as StoryNodeData | undefined)?.kind; return kind === "character" ? "#9a895f" : kind === "scene" ? "#759391" : kind === "asset" ? "#809957" : kind === "workflow" ? "#9386a2" : (dark ? "#b8df82" : "#789057"); }} /> : null}
  </ReactFlow>;
}

export function MapView({ assets, workflows, onOrganizeStory }: { assets: Asset[]; workflows: Workflow[]; onOrganizeStory?: () => void }) {
  const { activeProjectId, projects, setSelection, setView, theme } = useDariusStore();
  const project = projects.find((item) => item.id === activeProjectId);
  const characters = useCharacters(activeProjectId);
  const scenes = useScenes(activeProjectId);
  const scope = `map:${activeProjectId}`;
  const [directoryOpen, setDirectoryOpen] = useWorkspaceState(`${scope}:directory`, true);
  const [expanded, setExpanded] = useState(false);
  const [altitude, setAltitude] = useWorkspaceState<MapAltitude>(`${scope}:altitude`, "world");
  const [dive, setDive] = useWorkspaceState<MapDive>(`${scope}:dive`, null);
  const [search, setSearch] = useWorkspaceState(`${scope}:search`, "");
  const [selectedId, setSelectedId] = useWorkspaceState<string | null>(`${scope}:selected`, null);
  const projectLayout = useMapLayout((state) => activeProjectId ? state.projects[activeProjectId] : undefined);
  const dialog = useRef<HTMLDialogElement>(null);
  const expandButton = useRef<HTMLButtonElement>(null);
  const flow = useRef<ReactFlowInstance<Node<StoryNodeData>> | null>(null);
  useEffect(() => { useDariusStore.getState().setInspectorOpen(false); }, []);
  const graph = useMemo(() => buildStoryMap(project, characters.data ?? [], scenes.data ?? [], assets, workflows), [project, characters.data, scenes.data, assets, workflows]);
  const focused = useMemo(() => focusStoryMap(graph, altitude, dive), [graph, altitude, dive]);
  const visible = focused.nodes;
  const visibleIds = useMemo(() => new Set(visible.map((node) => node.id)), [visible]);
  const edges = useMemo(() => focused.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)), [focused.edges, visibleIds]);
  const matches = visible.filter((node) => `${node.data.label} ${node.data.subtitle}`.toLowerCase().includes(search.toLowerCase()));
  const selected = graph.nodes.find((node) => node.id === selectedId);
  const related = graph.edges.filter((edge) => edge.source === selectedId || edge.target === selectedId);
  const nodes = useMemo(() => visible.map((node) => ({ ...node, position: projectLayout?.[node.id] ?? node.position })), [visible, projectLayout]);
  const dimKey = search ? matches.map((node) => node.id).join(",") : "";
  const divedNode = dive ? graph.nodes.find((node) => node.id === `${dive.kind}:${dive.entityId}`) : null;
  const altitudeMeta = mapAltitudes.find((item) => item.id === altitude);

  useEffect(() => {
    const dialogElement = dialog.current;
    if (expanded) dialogElement?.showModal();
    else if (dialogElement?.open) { dialogElement.close(); expandButton.current?.focus(); }
    return () => {
      if (dialogElement?.open) dialogElement.close();
    };
  }, [expanded]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape" || expanded || document.querySelector("dialog[open]") || (event.target instanceof HTMLElement && event.target.closest("input, textarea, select"))) return;
      if (dive) { setDive(null); setSelectedId(null); event.preventDefault(); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dive, expanded, setDive, setSelectedId]);

  function focusNode(node: Node<StoryNodeData>) {
    setSelectedId(node.id);
  }
  function enterNode(node: Node<StoryNodeData>) {
    if (!canDive(node.data.kind)) { setSelectedId(node.id); return; }
    setSearch("");
    setDive({ kind: node.data.kind, entityId: node.data.entityId });
    setSelectedId(node.id);
    if (node.data.kind === "character") setAltitude("cast");
    if (node.data.kind === "scene") setAltitude("places");
    if (node.data.kind === "asset") setAltitude("media");
  }
  function changeAltitude(next: MapAltitude) {
    setSearch("");
    setAltitude(next);
    setDive(null);
    setSelectedId(null);
  }
  function openLibrary() { setExpanded(false); if (onOrganizeStory) onOrganizeStory(); else setView("create"); }
  function arrangeMap() {
    if (!activeProjectId) return;
    useMapLayout.getState().placeNodes(activeProjectId, arrangeNodes(nodes));
    window.requestAnimationFrame(() => void flow.current?.fitView({ padding: .16, maxZoom: 1, duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 320 }));
  }
  const workbench = <div className="map-workbench os-window">
    <div className="map-toolbar">
      <div className="map-layer-tabs" aria-label="Map levels">{mapAltitudes.map((item) => <button key={item.id} aria-pressed={altitude === item.id && !dive} onClick={() => changeAltitude(item.id)} title={item.hint} type="button">{item.label}</button>)}</div>
      <div className="map-toolbar-actions"><button className="map-arrange" onClick={arrangeMap} type="button"><LayoutGrid size={16} /> Arrange</button><button className="icon-button" aria-label={directoryOpen ? "Hide map contents" : "Show map contents"} aria-pressed={directoryOpen} title="Toggle contents" onClick={() => setDirectoryOpen(!directoryOpen)} type="button"><List size={18} /></button><button aria-label="Fit map to view" title="Fit map to view" className="icon-button" onClick={() => void flow.current?.fitView({ padding: .15, maxZoom: 1, duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 250 })} type="button"><Focus size={18} /></button><button ref={expanded ? undefined : expandButton} aria-label={expanded ? "Exit fullscreen map" : "Expand map"} title={expanded ? "Exit fullscreen map (Escape)" : "Expand map"} className="icon-button" onClick={() => setExpanded(!expanded)} type="button">{expanded ? <Minimize2 size={18} /> : <Maximize2 size={18} />}</button></div>
    </div>
    <nav className="map-breadcrumb" aria-label="Map depth">
      {dive ? <button className="map-back" onClick={() => { setDive(null); setSelectedId(null); setSearch(""); }} type="button"><ArrowLeft size={14} /> Back to {altitudeMeta?.label}</button> : null}
      <button className={!dive && altitude === "world" ? "current" : ""} onClick={() => changeAltitude("world")} type="button">World</button>
      {altitude !== "world" || dive ? <><ChevronRight size={12} /><button className={!dive ? "current" : ""} onClick={() => { setDive(null); }} type="button">{altitudeMeta?.label ?? "Level"}</button></> : null}
      {divedNode ? <><ChevronRight size={12} /><span className="current">{divedNode.data.label}</span></> : null}
      <span className="map-breadcrumb-hint">{dive ? "Press Escape to go back" : altitudeMeta?.hint}</span>
    </nav>
    <div className={`map-layout ${selected ? "has-map-detail" : ""} ${directoryOpen ? "" : "directory-hidden"}`}>
      <aside className="map-directory" aria-label="Map contents" hidden={!directoryOpen}>
        <label className="map-search"><Search size={15} /><input aria-label="Search map" placeholder="Find in your story…" value={search} onChange={(event) => setSearch(event.target.value)} />{search ? <button className="icon-button" aria-label="Clear map search" onClick={() => setSearch("")} type="button"><X size={14} /></button> : null}</label>
        <div className="map-directory-heading"><span>{dive ? divedNode?.data.label ?? "Territory" : altitudeMeta?.label}</span><span>{matches.length}</span></div>
        <div className="map-directory-list">{matches.map((node) => <button key={node.id} className={node.id === selectedId ? "selected" : ""} onClick={() => focusNode(node)} onDoubleClick={() => enterNode(node)} type="button"><i className={`map-dot dot-${node.data.kind}`} /><span><strong>{node.data.label}</strong><small>{node.data.kindLabel}{canDive(node.data.kind) ? " · enter" : ""}</small></span><ArrowUpRight size={12} /></button>)}{!matches.length ? <p className="map-search-empty">No matches. Try another name or level.</p> : null}</div>
        <button className="map-organize" onClick={openLibrary} type="button"><Boxes size={15} /> Organize story <ArrowUpRight size={13} /></button>
      </aside>
      <div className="story-canvas" aria-label="Project relationship map">
        <MapCanvas key={`${activeProjectId}:${altitude}:${dive?.kind ?? "surface"}:${dive?.entityId ?? ""}:${expanded}`} viewportKey={`${scope}:viewport:${altitude}:${dive?.kind ?? "surface"}:${dive?.entityId ?? ""}`} nodes={nodes} edges={edges} draggable={!dive} selectedId={selectedId} dimKey={dimKey} theme={theme} onMove={(id, point) => { if (activeProjectId && !dive) useMapLayout.getState().moveNode(activeProjectId, id, point); }} onSelect={(node) => setSelectedId(node.id)} onOpen={enterNode} onClear={() => setSelectedId(null)} onReady={(instance) => { flow.current = instance; }} />
        <div className="map-compass" aria-hidden="true"><Compass size={16} /><span>N</span></div>
        <div className="map-canvas-caption">{dive ? "Select a card to inspect · Use Back to return" : "Drag a card to place it · Arrange lines them up"}</div>
      </div>
      {selected ? <aside className="map-detail" aria-label="Map selection details"><header><span>{selected.data.kindLabel}</span><button className="icon-button" aria-label="Close map details" onClick={() => setSelectedId(null)} type="button"><X size={16} /></button></header>{selected.data.asset ? <div className="map-detail-preview"><AssetPreview key={selected.data.asset.id} asset={selected.data.asset} /></div> : null}<h2>{selected.data.label}</h2><span className="map-detail-badge">{selected.data.badge}</span><p>{selected.data.description || selected.data.subtitle}</p>{selected.data.prompt ? <><h3>Creative direction</h3><p className="map-prompt">{selected.data.prompt}</p></> : null}<h3>Connections · {related.length}</h3>{!related.length ? <p>No connections yet.</p> : null}<div className="map-related">{related.map((edge) => { const other = graph.nodes.find((node) => node.id === (edge.source === selectedId ? edge.target : edge.source)); return other ? <button key={edge.id} onClick={() => { setSearch(""); setSelectedId(other.id); if (canDive(other.data.kind)) enterNode(other); }} type="button"><small>{String(edge.label)}</small><span>{other.data.label}<ArrowUpRight size={13} /></span></button> : null; })}</div>{canDive(selected.data.kind) ? <button className="primary-button" onClick={() => enterNode(selected)} type="button">Enter this {selected.data.kind} <ArrowUpRight size={14} /></button> : null}{selected.data.kind === "asset" || selected.data.kind === "character" ? <button className="secondary-button" onClick={() => { setExpanded(false); setSelection({ type: selected.data.kind === "asset" ? "asset" : "character", id: selected.data.entityId }); setView("create"); }} type="button">Open in Create <ArrowUpRight size={14} /></button> : null}{selected.data.asset ? <button className="secondary-button" onClick={() => { setExpanded(false); if (selected.data.asset) setSelection({ type: "asset", id: selected.data.asset.id }); setView("edit"); }} type="button">Open in Edit <ArrowUpRight size={14} /></button> : null}<button className="secondary-button" onClick={() => { setExpanded(false); setSelection({ type: selected.data.kind, id: selected.data.entityId }); }} type="button">More details <ArrowUpRight size={14} /></button></aside> : null}
    </div>
    <footer className="map-footer"><span><i className="map-dot dot-character" /> Character <i className="map-dot dot-scene" /> Scene <i className="map-dot dot-asset" /> Media</span><span>{dive ? "Territory" : altitudeMeta?.label} · {visible.length} items · {edges.length} connections</span></footer>
  </div>;

  return <div className="view map-view story-map-view">
    <header className="view-heading"><div><span className="eyebrow">The world you’re building</span><h1>Your story, connected.</h1><p>Explore your characters, scenes, and media. Follow a connection to see the story behind it.</p></div><button className="secondary-button" onClick={openLibrary} type="button"><Boxes size={16} /> Organize story</button></header>
    {characters.isLoading || scenes.isLoading ? <LoadingState label="Loading your story…" /> : null}
    {characters.error || scenes.error ? <ErrorState message="Some story details could not be loaded." onRetry={() => { void characters.refetch(); void scenes.refetch(); }} /> : null}
    {!project ? <EmptyState title="Give your story a home" description="Choose a project above to explore its characters, scenes, and media." /> : !expanded ? workbench : null}
    <dialog className="map-expanded-dialog" aria-label="Expanded story map" ref={dialog} onCancel={() => setExpanded(false)} onClose={() => setExpanded(false)}>{expanded ? workbench : null}</dialog>
  </div>;
}
