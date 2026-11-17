// A stand-in for the Darius API with fictional sample data, so the interface can be
// viewed and smoke-tested without the backend, ComfyUI or any model.
//
//   node scripts/fixture-api.mjs [--port 8000]
//
// Nothing is written to disk. Canvas layout (positions, notes, frames) is kept in
// memory until the process stops; other writes are echoed back. Never point a real
// project at it.
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";

const now = "2026-11-17T10:00:00Z";
const project = (id, name, description) => ({ id, name, description, creative_brief: "", visual_style: "Painterly, soft light", default_aspect_ratio: "16:9", default_fps: 24, created_at: now, updated_at: now });
const projects = [project("p1", "Moss Kingdom", "A short film about a forest gate"), project("p2", "Night Market", "Street food at night"), project("p3", "Glass Desert", "A science-fiction trailer")];
const palette = [["#2f5d3a", "#c9e4a4"], ["#3b2f5d", "#e4b4a4"], ["#5d4a2f", "#f4d58a"], ["#1f4a5d", "#9fd8e4"], ["#5d2f3f", "#f0a9b8"]];
const names = ["Forest gate", "Mara portrait", "Lantern study", "River crossing", "Moss throne"];
const assets = names.map((name, i) => ({ id: `a${i + 1}`, project_id: "p1", kind: "image", role: "generation", path: `/fixture/a${i + 1}`, content_hash: `a${i + 1}`.padEnd(64, "0"), mime_type: "image/svg+xml",
  width: 1024, height: i % 2 ? 1365 : 1024, duration: null, fps: null, sample_rate: null, parent_asset_ids: [], scene_id: null, shot_id: null, provider: "local-comfyui", workflow_run_id: null,
  approval_state: "approved", metadata: { display_name: name }, created_at: `2026-11-1${i}T10:00:00Z` }));
const run = (id, assetId, extra = {}) => ({ id, jobId: `${id}-job`, revision: 2, seed: 4242, status: "completed", statusMessage: "Completed", error: null, assetIds: [assetId], ...extra });
const layout = [{ id: "r1", kind: "object", rect: [120, 160, 380, 520] }, { id: "r2", kind: "character", rect: [560, 220, 320, 640] }, { id: "r3", kind: "text", rect: [140, 80, 740, 90] }];
const board = (id, name, extra = {}) => ({ id, projectId: "p1", documentId: `doc-${id}`, name, kind: "moss-t2i", revision: 2, documentRevision: 2, settings: { adapterVersion: "moss-bboxes-v1", seed: null, references: [] },
  archived: false, artboard: { width: 1024, height: 1024, preset: "square" }, prompt: "", regionCount: 3, layout, activeResult: null, previewAssetId: null, latest: null, jobs: [], newResult: false, ...extra });
const boards = [
  board("b1", "Forest gate", { prompt: "An ancient gate swallowed by moss, morning fog", activeResult: run("g1", "a1"), previewAssetId: "a1", recentAssetIds: ["a1", "a3", "a5"] }),
  board("b2", "Mara portrait", { prompt: "Portrait of Mara, the keeper", activeResult: run("g2", "a2"), previewAssetId: "a2", settings: { adapterVersion: "moss-bboxes-v1", seed: null, references: [{ id: "ref1", sourceBoardId: "b1", sourceGenerationId: "g1", assetId: "a1", assetVersionId: "a1", role: "visual-note" }] } }),
  board("b3", "Lantern study", { prompt: "A lantern glowing between roots", jobs: [run("g3", "a3", { status: "running", statusMessage: "Sampling 14/28" })] }),
  board("b4", "Throne room", { kind: "fibo-t2i", settings: { adapterVersion: "fibo-dev-v1", seed: null, references: [] }, regionCount: 0, layout: [] }),
];
const placements = [{ boardId: "b1", x: 40, y: 60, displayWidth: 360, displayHeight: 450, order: 0 }, { boardId: "b2", x: 520, y: 20, displayWidth: 340, displayHeight: 470, order: 1 },
  { boardId: "b3", x: 280, y: 580, displayWidth: 360, displayHeight: 420, order: 2 }, { boardId: "b4", x: 760, y: 560, displayWidth: 320, displayHeight: 400, order: 3 }];
const workspace = { projectId: "p1", schemaVersion: 1, revision: 3, placements, annotations: [
  { id: "frame-scene-1", kind: "frame", x: 0, y: -10, width: 900, height: 540, text: "Scene 1 · The gate", color: "moss" },
  { id: "note-dawn", kind: "note", x: 1120, y: 80, width: 240, height: 170, text: "The gate only opens at dawn. Keep the light low and gold.", color: "sun" },
], boards, capacity: 1, queuePolicy: "single" };
const jobs = [{ id: "g3-job", project_id: "p1", job_type: "canvas", provider: "local-comfyui", status: "running", progress: .46, status_message: "Sampling 14/28", display_name: "Lantern study", output_asset_ids: [], external_job_id: null, error_code: null, error_detail: null, created_at: now, updated_at: now }];
const doc = id => ({ id, projectId: "p1", revision: 2, content: { name: "Board", globalPrompt: "", artboard: { preset: "square", width: 1024, height: 1024 }, regions: [] }, activeGenerationId: null, updatedAt: now, generations: [] });
const timelineVersion = { id: "v2", timeline_id: "t1", version_number: 2, state: "draft", edit_summary: "", created_by: "user", created_at: now, tracks: [
  { kind: "video", clips: [{ id: "c1", source_asset_id: "a1", source_in: 0, source_out: 5, timeline_in: 0, timeline_out: 5 }, { id: "c2", source_asset_id: "a2", source_in: 0, source_out: 4, timeline_in: 5, timeline_out: 9 }, { id: "c3", source_asset_id: "a4", source_in: 0, source_out: 6, timeline_in: 9, timeline_out: 15 }] },
  { kind: "audio", clips: [] }] };

function art(id) {
  const i = Math.max(0, assets.findIndex(a => a.id === id)) % palette.length, [deep, light] = palette[i];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${light}"/><stop offset="1" stop-color="${deep}"/></linearGradient><radialGradient id="s" cx=".7" cy=".3" r=".35"><stop offset="0" stop-color="#fff8e0" stop-opacity=".9"/><stop offset="1" stop-color="#fff8e0" stop-opacity="0"/></radialGradient></defs><rect width="1024" height="1024" fill="url(#g)"/><rect width="1024" height="1024" fill="url(#s)"/><path d="M0 760 C 200 640 360 700 520 620 S 860 560 1024 640 V1024 H0Z" fill="${deep}" opacity=".85"/><path d="M0 860 C 260 780 480 840 700 780 S 960 760 1024 800 V1024 H0Z" fill="#0b1a10" opacity=".55"/></svg>`;
}

const routes = [
  [/^\/health$/, () => ({ status: "ok", components: { api: { ready: true }, comfyui: { ready: true } } })],
  [/^\/projects$/, () => projects],
  [/^\/projects\/(p\d)$/, m => projects.find(p => p.id === m[1]) ?? projects[0]],
  [/^\/assets$/, (m, q) => q.get("project_id") === "p1" ? assets : []],
  [/^\/jobs$/, (m, q) => q.get("project_id") === "p1" ? jobs : []],
  [/^\/projects\/p1\/canvas-workspace$/, () => workspace],
  [/^\/projects\/p\d\/canvas-workspace$/, () => ({ ...workspace, placements: [], boards: [] })],
  [/^\/projects\/p\d\/canvases\/(doc-\w+)$/, m => doc(m[1])],
  [/^\/canvas\/engine$/, () => ({ adapterVersion: "moss-bboxes-v1", presets: [{ id: "square", name: "Square", width: 1024, height: 1024 }] })],
  [/^\/canvas\/image\/engine$/, () => ({ profiles: [], presets: [] })],
  [/^\/projects\/p1\/characters$/, () => [{ id: "c1", project_id: "p1", name: "Mara", description: "", approved_reference_asset_ids: ["a2"] }, { id: "c2", project_id: "p1", name: "Oren", description: "", approved_reference_asset_ids: [] }]],
  [/^\/projects\/p1\/ideas$/, () => [{ id: "i1", projectId: "p1", revision: "1", title: "The gate only opens at dawn", content: "", sourceMessageId: "", sourceText: "", conversationId: "", archived: false, updatedAt: now }]],
  [/^\/assets\/(\w+)\/derivatives$/, () => ({ derivatives: [] })],
  [/^\/timelines$/, (m, q) => q.get("project_id") === "p1" ? [{ id: "t1", project_id: "p1", scene_id: null, name: "Project assembly", created_at: now, updated_at: now }] : []],
  [/^\/timelines\/t1\/versions$/, () => [timelineVersion]],
  [/^\/settings\/llm$/, () => ({ provider: "ollama", model: "ornith-1.5-9b", ready: true, credential_configured: true, source: "saved", providers: [{ id: "ollama", label: "Ollama (local)", models: ["ornith-1.5-9b"], credential_configured: true }] })],
  [/^\/workflow-recipes$/, () => ({ workflows: [], folder: "", note: "" })],
  [/^\/(settings\/workflow-defaults|projects\/p\d\/trusted-workflows)$/, () => ({ enabled: false, entries: [] })],
  [/^\/projects\/p\d\/local-rendering$/, () => ({ enabled: false })],
];

// Writes echo back what a real save would return, without storing anything, so the
// interface behaves normally (drawing regions, switching workflows, moving boards).
const writes = [
  [/^\/projects\/p\d\/canvases\/(doc-\w+)\/save$/, (m, body) => ({ ...doc(m[1]), revision: (body.revision ?? 2) + 1, content: body.content ?? doc(m[1]).content })],
  [/^\/projects\/p\d\/canvas-workspace\/layout$/, (m, body) => {
    // Kept in memory so notes, frames and positions survive the next poll.
    workspace.revision += 1;
    if (body.placements) workspace.placements = body.placements;
    if (body.annotations) workspace.annotations = body.annotations;
    return workspace;
  }],
  [/^\/projects\/p\d\/canvas-workspace\/boards\/(\w+)$/, (m, body) => { const found = boards.find(b => b.id === m[1]) ?? boards[0]; return { ...found, revision: (body.revision ?? found.revision) + 1, settings: body.settings ?? found.settings, archived: body.archived ?? found.archived }; }],
  [/^\/projects\/p\d\/canvas-workspace\/boards$/, (m, body) => {
    const id = `b${Date.now().toString(36)}`, added = board(id, body.name ?? "Untitled board", { settings: body.settings ?? board(id, "").settings, layout: [], regionCount: 0 });
    return { boardId: id, workspace: { ...workspace, revision: workspace.revision + 1, boards: [...boards, added], placements: [...placements, { boardId: id, x: body.x ?? 0, y: body.y ?? 0, displayWidth: 360, displayHeight: 450, order: placements.length }] } };
  }],
];
const readBody = req => new Promise(resolve => { let raw = ""; req.on("data", chunk => { raw += chunk; }); req.on("end", () => { try { resolve(raw ? JSON.parse(raw) : {}); } catch { resolve({}); } }); });

export function startFixtureApi(port = 8000, host = "127.0.0.1") {
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, "http://fixture"), path = url.pathname.replace(/^\/api\/v1/, "");
    if (req.method !== "GET") {
      for (const [pattern, handler] of writes) {
        const m = path.match(pattern);
        if (m) { const body = await readBody(req); res.writeHead(200, { "content-type": "application/json" }); res.end(JSON.stringify(handler(m, body))); return; }
      }
    }
    if (path === "/events/stream") {
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" }); res.write(": fixture\n\n");
      const ping = setInterval(() => res.write(": ping\n\n"), 15000); req.on("close", () => clearInterval(ping)); return;
    }
    const content = path.match(/^\/assets\/(\w+)\/content$/);
    if (content) { res.writeHead(200, { "content-type": "image/svg+xml" }); res.end(art(content[1])); return; }
    for (const [pattern, handler] of routes) {
      const m = path.match(pattern);
      if (m) { res.writeHead(200, { "content-type": "application/json" }); res.end(JSON.stringify(handler(m, url.searchParams))); return; }
    }
    // Anything else: an empty list for reads, an empty object for writes.
    res.writeHead(200, { "content-type": "application/json" });
    res.end(req.method === "GET" ? "[]" : "{}");
  });
  return new Promise((resolve, reject) => { server.once("error", reject); server.listen(port, host, () => resolve(server)); });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const flag = process.argv.indexOf("--port"), port = flag > 0 ? Number(process.argv[flag + 1]) : 8000;
  startFixtureApi(port).then(() => console.log(`Darius fixture API on http://127.0.0.1:${port} (fictional data, nothing is stored)`),
    error => { console.error(error.code === "EADDRINUSE" ? `Port ${port} is busy. Is the real Darius API running? Stop it or pass --port.` : error.message); process.exit(1); });
}
