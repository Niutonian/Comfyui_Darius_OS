# Darius Canvas · first MOSS release

Implemented 22 October 2026 from `DARIUS_CANVAS_MOSS_CODEX_HANDOFF.md` and the supplied standard/focus mockups. Open **Create → Canvas → New empty canvas**. The user example is deliberately opt-in through the Layers panel.

## Editing and presentation

- Editable document, not a collection of generated image layers. Up to 64 nested group/object/character/text regions; geometry is stored as fractions of each parent. Groups are structural and omitted from MOSS rows.
- Draw on the artboard or explicitly inside the selected region. Select, pan, drag, resize, exact text, descriptions, pixel geometry, parent selection, visibility, inherited locks, layer order, duplicate/delete and undo/redo. Keyboard: V/H/R/T, arrows (Shift = 10 pixels), Delete, Ctrl/Cmd+D, Ctrl/Cmd+Z and Shift+Z. Field typing does not delete regions.
- Standard workspace and fullscreen focus share one draft, undo stack, selection, viewport, jobs and the existing project chat/composer. Focus is not browser fullscreen. Temporary panels and focus can be closed with Escape; typing fields retain normal editing behavior. Keyboard focus is trapped in the focus workspace.
- Both themes and phone layouts use the existing Darius tokens. Constrained layouts use optional Layers and inspector sheets. The camera only refits initially or on explicit Fit; moving guides never moves existing pixels.
- Autosave with immutable server revisions and optimistic concurrency. Another device's dirty update is never silently overwritten. Export the draft or explicitly reload the saved revision to resolve a conflict. JSON import/export retains hierarchy and exact text.
- Generate composition is explicit, saves first and refuses an older snapshot if the draft changes during that save. No generation is submitted by drawing, dragging or normal autosave.

## Exact source and graph changes

The original UI workflow remains byte-identical:

`workflows/defaults/image_moss_image_t2i_bboxes.json`

SHA-256: `2077e236a84a8518e4614a35f7cb52b2a1b953da226c51eee02246e89f08ca0d`.

The ZIP was not present in the supplied folder. Its previously imported API graph and manifest were recovered from Darius's existing recipe caches. Canonical graph/package digests were checked against the existing Block Party import record. No inferred UI-to-API reconstruction was substituted. Recovery details and immutable snapshots live in `workflows/canvas/moss-bboxes-v1/`.

Canonical source graph SHA-256: `3e2dc435a1509ad3ac8d31a45a1d7d2ed01e007c5cad0a48c17b2d00f0c09f0b`.

Only these inputs may differ in the prepared graph:

| Input | Working-copy behavior |
| --- | --- |
| `19.aspect_ratio` | One of eight installed, validated 1 MP presets; dimensions rounded to multiples of 16 |
| `25.editor_state` | Current flattened pixel boxes inside the verified `__value__` literal wrapper |
| `25.last_incoming` | Empty wrapped array, never stale example state |
| `27.prompt` | Exact document-wide description |
| `27.character_boxes` | 1-based indices across **all semantic rows**, including text; no default character leaks |
| `18:16.switch` | Always false: compiled layout bypasses the prose enhancer |
| `18:7.seed` | Concrete 32-bit integer, resolved once per new request |
| `9.filename_prefix` | Job/project-scoped output name, assigned by the existing provider |

The original 25 steps, CFG 2.5, er_sde/simple, denoise 1 and enabled SLG (single layer 22, 0–0.5) remain unchanged. No prompt rewriting or model planner is used for a Canvas render. Source and prepared graph digests, sampler/model/SLG parameters, region index map, concrete seed, final compiled layout, Comfy prompt ID and execution graph digest are retained. New completions also capture best-effort runtime version/device identity; unavailable identity is explicitly marked, not invented. The three initial GPU acceptance records predate the additional runtime-metadata fields; their independently captured runtime identity is in the CPU verification report.

## Runtime boundary and storage

`canvas_document.py` validates and resolves geometry independently of the editor. `canvas_moss.py` is the versioned graph adapter. `canvas_api.py` owns project/document requests and snapshots; the browser cannot submit arbitrary graph changes through these routes.

The existing workflow registry, jobs, targeted local worker, GPU lease, Comfy MCP validation/history and asset ingestion are reused. Generated Canvas contracts are internal-only: they can be executed by their saved Canvas job but are excluded from the normal chat/model workflow list. They must not become reusable templates for a later subject.

Database migration `b16d7a5e384d` adds `canvas_documents`, `canvas_revisions` and `canvas_generations`. Generation creation and its receipt commit together. Unique document/request keys make transport retries return the same job and seed. A worker-launch failure leaves a queued, recoverable receipt with Start worker in version history. Failed/interrupted jobs retain the document and last successful result; partial outputs are not selected.

Collection is restricted to declared SaveImage node **9** from the matching Comfy history prompt, never the newest shared PNG or preview output. Asset ownership is checked against the project. Completion only auto-selects a result if its immutable source revision and the user's selection version still match. Editing during a run cannot roll geometry back; older results remain available in history. Compare uses genuine stored results.

## Verified installation

Checked installed source/schema and executed previews, not just generated node documentation:

- ComfyUI **0.42.4**, Windows, Python **3.12.10**, PyTorch **2.9.1+cu130**, NVIDIA RTX 5080 16 GB.
- `CreateBoundingBoxes` accepts wrapped pixel state, normalizes once, and rounds to its normalized grid. `MOSSImageLayoutPrompt` emits center-relative integer `yxyx` boxes and preserves exact Unicode/newlines. Character indices enumerate all semantic rows.
- The lazy switch's false branch reaches positive encoding unchanged. `ResolutionSelector` uses 1024² target pixels, aspect scaling and ties-to-even rounding to multiples of 16.
- Installed model names and declared file sizes were checked: `moss_image_sft_int8_convrot.safetensors`, `qwen3.5_9b_w4a8_gptq.safetensors`, `flux2-vae_small.safetensors`. This was not a fresh SHA-256 verification of every installed model file.
- No model downloads, ComfyUI changes/restart, voice-service restart or Block Party repository edits were needed.

## Evidence and repeatable checks

CPU-only `scripts/check-canvas-runtime.py` validates the complete prepared graph, then executes only layout/positive-preview dependencies for two contrasting layouts. Both passed with identical compiled layout and positive-preview text. No sampler, decoder or SaveImage is included in those preview runs. Report: `data/canvas-runtime-check/report.json`.

Explicit GPU check `scripts/check-canvas-generations.py --run` completed **three real local generations**, all 1 MP / 25 steps / seed 42:

1. Red cube on the left; edit to the right during the first run. Completion retained the newer document and did not auto-select the old revision.
2. Same cube moved right at the same seed. Compiled coordinates and image placement both changed. Repeating the submission key returned the same job.
3. Portrait 832 × 1248: title `MONDE\n世界`, ceramic robot character and amber object. Exact text and the character-row mapping survived compilation. The resulting lettering was readable and the requested elements appeared. The requested sphere was visually flattened/ellipsoidal rather than a perfect sphere: successful execution is not a guarantee of shape or box adherence.

GPU report and paths: `data/canvas-runtime-check/generation-report.json`. Runs use an isolated database/definitions directory under `data/canvas-acceptance/` and project `74df2cd6-954c-4ae6-a155-5d1f7749e056`, not any existing user project. Images remain in that isolated project's generated-assets directory. No cloud API or render credits were used.

Automated checks:

- 24 Canvas backend tests: geometry, invalid limits, cycles, inherited visibility/locks, Unicode/indexing, graph allowlist, source immutability, save/reopen/CAS, idempotency, failed preflight, worker recovery, interrupted jobs, internal-only recipes, ownership and declared-output collection/provenance.
- Broader backend regression: **175 tests passed**, covering workflow registry, preflight, assets, GPU handoff, vertical slice, executor/reliability, base routing and Block Party; migration upgrade/downgrade round-trip included.
- Full web suite: **235 tests / 57 files passed**, including 9 geometry/history tests and 3 Canvas editor tests for save/generation races, transport retry identity and focus continuity.
- Four real-browser interaction cases: light/dark × desktop 1600 × 1100 and phone 412 × 915. Drawing, nesting, exact text, autosave, duplicate, undo/redo, no unsupported editing controls, camera continuity and shared chat draft passed. Another four cases checked genuine generated results in both presentations. Repeated against the production build, with API writes isolated from the live database.
- Full ESLint completed with no errors and five existing voice-hook dependency warnings. Typecheck and production build passed. Node prints the existing experimental localStorage warning during static prerender.

Screenshots: `data/screenshots/2026-10-22-canvas/implementation/` (`*-standard.png`, `*-focus.png`, `*-result-standard.png`, `*-result-focus.png`).

## Deliberate limits and follow-ups

- Whole-composition raster generation only. No mask, image-reference conditioning, outside-pixel preservation, per-region generation or independently generated RGBA layers. Document locks are not pixel locks. Nonempty palettes, arbitrary sizes and higher-MP generation are rejected rather than simulated.
- Layout is guidance, not a pixel-perfect constraint. Model-rendered typography/shape fidelity still needs visual review. Same seed does not guarantee identical bytes after hardware, model or software changes.
- Shared project chat is real chat, not a hidden geometry agent. It is explicitly labeled accordingly; geometry changes use Canvas tools. No separate voice engine/session was introduced.
- Unsaved UI continuity is memory-only. Saved revisions survive reload; keep the page open or export if offline autosave fails. Standard browser navigation warns on unsaved edits.
- Cancellation remains the existing per-job service behavior. No new global Comfy interrupt control was added. Missing-model, offline, worker-unavailable and interruption recovery paths are tested with controlled failures; no installed weights were renamed/deleted and ComfyUI was not deliberately crashed for acceptance.
- Source/model names are checked before submission, but readiness is not a VRAM guarantee. Unexpected ComfyUI errors are shown without throwing away the draft or last successful image.
- Added pinned Konva 10.9.0 / react-konva 19.0.10, compatible with the existing React 19.1.1. Rendering and transform semantics follow the official [React Konva guide](https://konvajs.org/docs/react/index.html) and [Transformer example](https://konvajs.org/docs/react/Transformer.html). React itself was not upgraded.
- `npm audit` reported 12 existing dependency advisories (including Next/sharp and development tooling), none in the added Konva packages. Broad security/framework upgrades were not mixed into Canvas; they remain separate maintenance work.

## Local deployment

Production build and migration applied. Database backup before migration:
`data/backups/darius-before-canvas-20261022-2316.db`.

Only API/web processes were replaced. API/web logs: `data/api-canvas-20261022.*.log`, `data/web-canvas-20261022.*.log`. The saved Ollama selection (`ornith-1.5:35b`) was unchanged. Production web/API and proxied Canvas engine checks succeeded, with eight presets and installed engine readiness true. Refresh an already-open browser tab to load the new section.

Temporary preview API/web servers (8004/3001) were stopped after verification. Their isolated database, definitions, real generated images, reports and screenshots are retained for inspection. Browser audit scripts require that isolated API to be started again; never point their project-creation checks at the live user database.

### 23 October: embedded chat scroll correction

The chat stream could extend below the Canvas panel (reproduced at 186 pixels below its lower edge), making its latest reply invisible even at scroll-bottom. The panel/host/workspace/conversation height chain is now bounded; the message stream owns a visible, theme-coloured scrollbar and contains its scrolling. Desktop conversation navigation remains available in a capped header area. Opening or reparenting an embedded panel follows the latest turn rather than inheriting an older Talk reading position; voice sends also re-enable following. Scrolling up still suspends automatic following until the user sends, reopens or selects Latest message.

`scripts/check-canvas-chat-scroll.cjs` uses in-browser Canvas/chat fixtures, never a real model or persistent API write. It checks desktop 1600 × 1100 and phone 412 × 915: bounds, overflowing scroll, latest on open, late content growth, manual history reading, sending from a closed panel and returning from focus. Both production-browser cases passed; stream bottoms were inside the panel (946 < 963 and 767 < 784). Screenshots: `data/screenshots/canvas-chat-scroll-{1600,412}.png`. All **236 web tests / 57 files**, typecheck and production build passed. ESLint has no errors and the same five existing voice-hook warnings. Only web was restarted; API, model selection, ComfyUI and voice services were untouched. Logs: `data/web-canvas-scroll-20261023.*.log`.
