import type { Edge, Node } from "@xyflow/react";
import type { Asset, Character, MapAltitude, Project, Scene, Workflow } from "./types";

export type StoryNodeData = {
  kind: "project" | "character" | "scene" | "asset" | "workflow";
  kindLabel: string; entityId: string; label: string; subtitle: string; badge: string;
  description?: string; prompt?: string; asset?: Asset;
};

export function buildStoryMap(project: Project | undefined, characters: Character[], scenes: Scene[], assets: Asset[], workflows: Workflow[]): { nodes: Node<StoryNodeData>[]; edges: Edge[] } {
  if (!project) return { nodes: [], edges: [] };
  const nodes: Node<StoryNodeData>[] = [];
  const edges: Edge[] = [];
  function add(data: StoryNodeData, x: number, y: number) {
    const id = `${data.kind}:${data.entityId}`;
    nodes.push({ id, type: "story", position: { x, y }, data });
    return id;
  }
  function connect(source: string, target: string, label: string) { edges.push({ id: `${source}:${target}:${label}`, source, target, label, type: "smoothstep", labelStyle: { fill: "#56694d", fontSize: 10 }, labelBgStyle: { fill: "#ecf1e6", fillOpacity: .95 }, labelBgPadding: [6, 3], labelBgBorderRadius: 4 }); }
  const root = add({ kind: "project", entityId: project.id, kindLabel: "Project", label: project.name, subtitle: project.description || "Your creative world", description: project.creative_brief || project.description, prompt: project.visual_style, badge: `${characters.length} characters · ${scenes.length} scenes` }, 0, 100);
  characters.forEach((character, index) => {
    const reference = assets.find((asset) => character.approved_reference_asset_ids.includes(asset.id) && asset.kind === "image");
    const id = add({ kind: "character", entityId: character.id, kindLabel: "Character", label: character.name, subtitle: character.description || "Define their story and visual identity", description: character.continuity_notes || character.description, prompt: character.canonical_prompt, badge: `${character.approved_reference_asset_ids.length} approved references`, asset: reference }, 360, index * 300);
    connect(root, id, "Character");
  });
  scenes.forEach((scene, index) => {
    const id = add({ kind: "scene", entityId: scene.id, kindLabel: `Scene ${String(scene.number).padStart(2, "0")}`, label: scene.title, subtitle: [scene.location, scene.time_of_day].filter(Boolean).join(" · ") || scene.description || "Plan the setting and action", description: scene.description, prompt: scene.screenplay_text, badge: scene.status }, 360, characters.length * 300 + index * 210);
    connect(root, id, "Scene");
  });
  assets.forEach((asset, index) => {
    const filename = String(asset.metadata.original_filename || asset.metadata.filename || "");
    const name = !filename || /^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(filename) ? `${asset.kind[0].toUpperCase()}${asset.kind.slice(1)} ${String(index + 1).padStart(2, "0")}` : filename;
    const id = add({ kind: "asset", entityId: asset.id, kindLabel: asset.role === "reference" ? "Reference" : asset.kind, label: name, description: filename || undefined, subtitle: [asset.width && asset.height ? `${asset.width} × ${asset.height}` : null, asset.duration ? `${asset.duration.toFixed(1)}s` : null, asset.provider === "local-comfyui" ? "Local generation" : asset.provider].filter(Boolean).join(" · "), badge: asset.approval_state, asset }, 700 + (index % 2) * 290, Math.floor(index / 2) * 300);
    const owners = characters.filter((character) => character.approved_reference_asset_ids.includes(asset.id));
    owners.forEach((character) => connect(`character:${character.id}`, id, "Approved reference"));
    const scene = scenes.find((scene) => scene.id === asset.scene_id);
    if (scene) connect(`scene:${scene.id}`, id, "Scene media");
    const parents = assets.filter((parent) => asset.parent_asset_ids.includes(parent.id));
    parents.forEach((parent) => connect(`asset:${parent.id}`, id, "Derived from"));
    if (!owners.length && !scene && !parents.length) connect(root, id, "Project media");
  });
  workflows.forEach((workflow, index) => {
    const id = add({ kind: "workflow", entityId: workflow.id, kindLabel: "Generation tool", label: workflow.name, subtitle: workflow.capability.replaceAll("-", " "), description: `Produces ${workflow.output.kind}. Review its inputs and approve a plan in Talk.`, badge: workflow.execution_provider === "local-comfyui" ? "Runs locally" : "Cloud provider" }, 0, 330 + index * 210);
    connect(id, root, "Available tool");
  });
  return { nodes, edges };
}

export type MapDive = { kind: StoryNodeData["kind"]; entityId: string } | null;

export const mapAltitudes: { id: MapAltitude; label: string; hint: string }[] = [
  { id: "world", label: "World", hint: "The project, its people, and its places" },
  { id: "cast", label: "Cast", hint: "Characters and the references that keep them consistent" },
  { id: "places", label: "Places", hint: "Scenes and the media that belongs to them" },
  { id: "media", label: "Media", hint: "Every generated and imported asset, with lineage" },
  { id: "tools", label: "Tools", hint: "Registered generation workflows" },
];

const arrangeColumn: Record<StoryNodeData["kind"], number> = {
  workflow: 0,
  project: 1,
  character: 2,
  scene: 3,
  asset: 4,
};

/** Place the current cards in readable columns without overlap. */
export function arrangeNodes(nodes: { id: string; data: { kind: StoryNodeData["kind"] } }[]) {
  const columns = new Map<number, string[]>();
  nodes.forEach((node) => {
    const column = arrangeColumn[node.data.kind];
    columns.set(column, [...(columns.get(column) ?? []), node.id]);
  });
  const positions: Record<string, { x: number; y: number }> = {};
  const columnWidth = 320;
  const rowHeight = 240;
  const tallest = Math.max(1, ...[...columns.values()].map((ids) => ids.length));
  columns.forEach((ids, column) => {
    const offset = ((tallest - ids.length) * rowHeight) / 2;
    ids.forEach((id, index) => {
      positions[id] = { x: column * columnWidth, y: offset + index * rowHeight };
    });
  });
  return positions;
}

export function storyNodeId(kind: StoryNodeData["kind"], entityId: string) {
  return `${kind}:${entityId}`;
}

function connectedIds(edges: Edge[], focusId: string) {
  const ids = new Set<string>([focusId]);
  edges.forEach((edge) => {
    if (edge.source === focusId) ids.add(edge.target);
    if (edge.target === focusId) ids.add(edge.source);
  });
  return ids;
}

function keepKinds(altitude: MapAltitude, kind: StoryNodeData["kind"], connectedToFocus: boolean) {
  if (kind === "project") return true;
  if (altitude === "world") return kind === "character" || kind === "scene";
  if (altitude === "cast") return kind === "character" || (kind === "asset" && connectedToFocus);
  if (altitude === "places") return kind === "scene" || (kind === "asset" && connectedToFocus);
  if (altitude === "media") return kind === "asset" || kind === "character" || kind === "scene";
  return kind === "workflow";
}

export function focusStoryMap(
  graph: { nodes: Node<StoryNodeData>[]; edges: Edge[] },
  altitude: MapAltitude,
  dive: MapDive,
): { nodes: Node<StoryNodeData>[]; edges: Edge[]; focusId: string | null } {
  if (!graph.nodes.length) return { nodes: [], edges: [], focusId: null };
  const project = graph.nodes.find((node) => node.data.kind === "project");
  if (dive) {
    const focusId = storyNodeId(dive.kind, dive.entityId);
    const focus = graph.nodes.find((node) => node.id === focusId);
    if (!focus) return { nodes: graph.nodes.filter((node) => node.data.kind === "project"), edges: [], focusId: project?.id ?? null };
    const neighborIds = connectedIds(graph.edges, focusId);
    if (project) neighborIds.add(project.id);
    const nodes = layoutTerritory(graph.nodes.filter((node) => neighborIds.has(node.id)), focusId);
    const ids = new Set(nodes.map((node) => node.id));
    return { nodes, edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)), focusId };
  }
  const characterIds = new Set(graph.nodes.filter((node) => node.data.kind === "character").map((node) => node.id));
  const sceneIds = new Set(graph.nodes.filter((node) => node.data.kind === "scene").map((node) => node.id));
  const related = (node: Node<StoryNodeData>) => {
    if (node.data.kind !== "asset") return false;
    return graph.edges.some((edge) => {
      const other = edge.source === node.id ? edge.target : edge.target === node.id ? edge.source : null;
      if (!other) return false;
      if (altitude === "cast") return characterIds.has(other);
      if (altitude === "places") return sceneIds.has(other);
      return false;
    });
  };
  const nodes = graph.nodes.filter((node) => keepKinds(altitude, node.data.kind, related(node)));
  const ids = new Set(nodes.map((node) => node.id));
  return { nodes, edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)), focusId: project?.id ?? null };
}

export function layoutTerritory(nodes: Node<StoryNodeData>[], focusId: string) {
  const focus = nodes.find((node) => node.id === focusId);
  if (!focus) return nodes;
  const project = nodes.filter((node) => node.data.kind === "project" && node.id !== focusId);
  const rest = nodes.filter((node) => node.id !== focusId && node.data.kind !== "project");
  return [
    { ...focus, position: { x: 320, y: 210 } },
    ...project.map((node) => ({ ...node, position: { x: 20, y: 210 } })),
    ...rest.map((node, index) => {
      const angle = (index / Math.max(rest.length, 1)) * Math.PI * 1.7 - .85;
      const radius = 260 + (index % 3) * 36;
      return { ...node, position: { x: 320 + Math.cos(angle) * radius, y: 210 + Math.sin(angle) * radius } };
    }),
  ];
}

export function canDive(kind: StoryNodeData["kind"]) {
  return kind === "project" || kind === "character" || kind === "scene" || kind === "asset";
}
