import { readFile } from "node:fs/promises";
import { test as base, expect } from '@playwright/test';
const stamp = '2026-01-01T00:00:00Z';
const prompt = 'A moonlit garden with glass flowers';
export const test = base.extend({
  sandbox: async ({ context, baseURL, page }, use) => {
    const unexpected = [], errors = [], submissions = [], transfers = [];
    const project = { id: 'smoke-project', name: 'Moon garden', description: '', created_at: stamp, updated_at: stamp, creative_brief: '', visual_style: '', default_aspect_ratio: '1:1', default_resolution: '1024x1024', default_fps: 24, settings: {}, character_count: 0, scene_count: 0, asset_count: 0 };
    const conversation = { id: 'smoke-chat', project_id: project.id, title: 'Garden ideas', created_at: stamp, updated_at: stamp };
    const content = { schemaVersion: 1, name: 'Garden composition', artboard: { preset: 'square', width: 1024, height: 1024 }, globalPrompt: prompt, regions: [] };
    const board = { id: 'smoke-board', projectId: project.id, documentId: 'smoke-document', name: content.name, kind: 'moss-t2i', revision: 1, documentRevision: 1, settings: { adapterVersion: 'moss-bboxes-v1', seed: 42, references: [] }, archived: false, artboard: content.artboard, prompt, regionCount: 0, layout: [], activeResult: null, previewAssetId: null, latest: null, jobs: [], newResult: false };
    const document = { id: board.documentId, projectId: project.id, revision: 1, content, activeGenerationId: null, updatedAt: stamp, generations: [] };
    const workspace = { projectId: project.id, schemaVersion: 1, revision: 1, placements: [{ boardId: board.id, x: 0, y: 0, displayWidth: 360, displayHeight: 450, order: 0 }], boards: [board], capacity: 256, queuePolicy: 'serial' };
    const fixtureAssets = [];
    const messages = [{ id: 'smoke-assistant', conversation_id: conversation.id, role: 'assistant', content: '```prompt Garden idea\n' + prompt + '\n```', metadata: { prompt_drafts: [{ id: 'draft-a', title: 'Garden idea', text: prompt }] }, created_at: stamp }];
    let projects = [project], generation = null, loseReply = false, lookups = 0;
    const json = (route, value, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) });
    await context.routeWebSocket('**/*', socket => { unexpected.push('WebSocket ' + socket.url()); socket.close(); });
    await context.addInitScript(({ project }) => localStorage.setItem('darius-interface-v1', JSON.stringify({ state: { theme: 'light', activeProjectId: project.id, projects: [project], view: 'home', knownJobIds: Array.from({ length: 50 }, (_, i) => 'historical-job-' + i), inspectorOpen: false, trayOpen: false }, version: 0 })), { project });
    page.on('pageerror', error => errors.push(error.message));
    context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), method = request.method();
      // Every API is fulfilled locally. Other origins are blocked even if the app misroutes.
      const prefix = '/api/darius/api/v1';
      if (url.origin !== baseURL || (!url.pathname.startsWith(prefix) && url.pathname.includes('/api/'))) {
        unexpected.push(method + ' ' + url.origin + url.pathname); return route.abort();
      }
      if (!url.pathname.startsWith(prefix)) return route.continue();
      const p = url.pathname.slice(prefix.length), payload = method === 'GET' ? null : request.postDataJSON();
      if (method === 'GET' && p === '/assets') return json(route, fixtureAssets);
      if (p === '/assets/smoke-preview/derivatives') return json(route, { derivatives: [] });
      if (p === '/assets/smoke-preview/content') return route.fulfill({ contentType: 'video/mp4', body: await readFile(new URL('../../apps/showcase/public/media/workstation-pov.mp4', import.meta.url)) });
      if (p === '/canvas/video/engine') return json(route, { modes: [], durations: [5,10,15] });
      if (p === '/canvas/image/engine') return json(route, { profiles: [], presets: [] });
      if (p === '/assets/smoke-image/content') return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="green"/></svg>' });
      if (method === 'GET' && (p === '/health')) return json(route, { status: 'ok', components: {} });
      if (p.endsWith('/events/stream')) return route.fulfill({ contentType: 'text/event-stream', body: ': isolated fixture\n\n' });
      if (p === '/projects' && method === 'POST') { const created = { ...project, ...payload, id: 'created-project' }; projects.push(created); return json(route, created, 201); }
      if (method === 'GET' && (p === '/projects')) return json(route, projects);
      if (method === 'GET' && (/^\/projects\/[^/]+$/.test(p))) return json(route, projects.find(item => item.id === p.split('/')[2]) ?? project);
      if (method === 'GET' && (p.endsWith('/assistant-context'))) return json(route, { notes: '', character_id: null, scene_id: null, shot_id: null, reference_asset_ids: [] });
      if (method === 'GET' && (p.endsWith('/local-rendering'))) return json(route, { project_id: project.id, enabled: false, mode: 'review' });
      if (method === 'GET' && (p === '/settings/llm')) return json(route, { provider: 'ollama', model: 'fixture', ready: true, credential_configured: true, source: 'environment', providers: [{ id: 'ollama', label: 'Ollama', models: ['fixture'], credential_configured: true }] });
      if (method === 'GET' && (p === '/workflow-recipes')) return json(route, { workflows: [], folder: 'workflows/defaults', note: 'Synthetic fixture' });
      if (p === '/settings/workflow-defaults' || p.endsWith('/trusted-workflows')) return json(route, { enabled: false, entries: [], global_defaults: { enabled: false, entries: [] } });
      if (p.endsWith('/conversations')) return json(route, method === 'POST' ? conversation : [conversation]);
      if (p.endsWith('/messages')) {
        if (method === 'POST') { const message = { ...payload, id: 'user-' + messages.length, conversation_id: conversation.id, created_at: stamp }; messages.push(message); return json(route, message); }
        return json(route, messages);
      }
      if (p.endsWith('/reply/stream')) {
        const answer = { ...messages[0], id: 'reply-' + messages.length, content: 'Let us explore the garden idea.', metadata: {} }; messages.push(answer);
        return route.fulfill({ contentType: 'application/x-ndjson', body: JSON.stringify({ type: 'done', message: answer }) + '\n' });
      }
      if (p.endsWith('/canvas-workspace/boards/' + board.id) && method === 'POST') { board.settings = payload.settings; board.revision++; return json(route, board); }
      if (method === 'GET' && (p.endsWith('/canvas-workspace'))) return json(route, workspace);
      if (method === 'GET' && (p.endsWith('/canvases'))) return json(route, [{ id: document.id, name: content.name, revision: document.revision, updatedAt: stamp }]);
      if (method === 'GET' && (p.endsWith('/canvases/' + document.id))) return json(route, document);
      if (method === 'GET' && (p === '/canvas/engine')) return json(route, { adapterVersion: 'moss-bboxes-v1', presets: [{ id: 'square', name: 'Square', width: 1024, height: 1024 }] });
      if (p.endsWith('/prompt')) {
        const target = { boardId: board.id, documentId: document.id, name: board.name, archived: false, boardRevision: board.revision, documentRevision: document.revision, destination: { key: 'globalPrompt', label: 'Composition prompt', family: 'MOSS', mode: 'text-to-image', maxLength: 30000 }, text: content.globalPrompt };
        if (method === 'GET') return json(route, target);
        transfers.push(payload); content.globalPrompt = payload.text; document.revision++; board.documentRevision++; board.prompt = payload.text;
        return json(route, { transferId: payload.transferId, undone: false, target: { ...target, text: payload.text }, board, document });
      }
      if (p.includes('/requests/')) { lookups++; return json(route, generation); }
      if (p.endsWith('/generate')) {
        submissions.push(payload);
        generation ??= { id: 'smoke-generation', jobId: 'smoke-job', revision: payload.revision, seed: payload.seed, status: 'queued', statusMessage: 'Queued fixture', error: null, assetIds: [], provenance: {}, createdAt: stamp };
        document.generations = [generation]; board.latest = generation; board.jobs = [generation];
        if (loseReply) { loseReply = false; return route.abort('connectionreset'); }
        return json(route, generation);
      }
      if (method === 'GET' && (p === '/jobs')) return json(route, []);
      if (/\/(assets|characters|scenes|shots|timelines|workflows|ideas)$/.test(p) && method === 'GET') return json(route, []);
      unexpected.push(method + ' ' + p); return json(route, { detail: 'Unimplemented smoke fixture: ' + p }, 501);
    });
    await use({ project, board, document, workspace, submissions, transfers, messages,
      configureVideoFailure: () => {
        const draft = { prompt: 'Original failed scene', camera: '', audio: '', inputs: [], seconds: 15, turbo: true, preset: 'wide', resolution: '720p', upscaleDevice: 'cuda' };
        const config = { schemaVersion: 1, family: 'minimax-h3', activeMode: 'reference-video', modeDrafts: Object.fromEntries(['animate-image','camera-direction','reference-video'].map(mode => [mode, structuredClone(draft)])) };
        board.kind = 'minimax-h3-video'; board.settings.adapterVersion = 'minimax-h3-reference-video-v1'; board.settings.video = config;
        generation = { id: 'failed-video', jobId: 'failed-video-job', revision: 1, seed: '18446744073709551615', status: 'failed', statusMessage: 'Final stage failed', error: 'MinimaxH3LatentUpscaler3D: Allocation on device', assetIds: ['smoke-preview'], provenance: { profileId: 'minimax-h3-reference-video-v1', partial: true, intermediateAssetIds: ['smoke-preview'], videoConfig: config, recovery: { stage: 'upscale', outOfMemory: true, message: 'Preview saved; final upscale ran out of GPU memory.', canResumeFinalOnly: false } }, createdAt: stamp };
        document.generations = [generation]; board.latest = { ...generation, intermediateAssetIds: ['smoke-preview'], recovery: generation.provenance.recovery };
      },
      configureEdit: () => {
        const draft = { prompt: '', negativePrompt: '', inputs: [], preset: 'square', megapixels: 1, steps: 25, cfg: 1, seed: null, enhance: false, styleEnabled: false, styleLora: '', styleStrength: 0, styleText: '', followSource: true, referenceResolution: 0 };
        board.kind = 'image-recipe'; board.settings.adapterVersion = 'qwen21-edit-v1';
        board.settings.image = { schemaVersion: 1, activeProfile: 'qwen21-edit-v1', drafts: Object.fromEntries(['flux3-klein-t2i-v1','krea2-turbo-t2i-v1','qwen21-t2i-v1','qwen21-edit-v1'].map(key => [key, structuredClone(draft)])) };
        fixtureAssets.push({ id: 'smoke-image', project_id: project.id, kind: 'image', role: 'reference', path: '/fixture.png', content_hash: 'a'.repeat(64), mime_type: 'image/png', width: 64, height: 64, duration: null, fps: null, sample_rate: null, parent_asset_ids: [], scene_id: null, shot_id: null, provider: 'fixture', workflow_run_id: null, approval_state: 'approved', metadata: { display_name: 'Synthetic reference' }, created_at: stamp });
      },
      loseNextReply: () => { loseReply = true; }, lookupCount: () => lookups,
      complete: () => { Object.assign(generation, { status: 'completed', statusMessage: 'Completed fixture', assetIds: ['smoke-image'] }); board.jobs = []; board.activeResult = generation; board.previewAssetId = 'smoke-image'; document.activeGenerationId = generation.id; },
    });
    expect(unexpected, 'All API traffic must have explicit local fixtures').toEqual([]);
    expect(errors, 'Browser runtime errors').toEqual([]);
  },
});
export { expect };
