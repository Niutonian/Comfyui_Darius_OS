# Project MOSS workspace

Implemented from `DARIUS_MULTI_BOARD_WORKSPACE_CODEX_HANDOFF.md` (23 October 2026). This extends the existing Canvas document/editor and MOSS adapter; it does not introduce a second region editor or a general workflow graph.

## What changes

Create → Canvas opens a project-owned pan/zoom workspace. Existing saved Canvas documents are placed in a readable grid on first access, retaining their IDs, regions, seeds, selected results and generation history. Initialization is idempotent; each document has one board owner.

Boards support Add, Open/double-click, rename, independent duplicate, header dragging, presentation-size/position controls, search/jump, Fit selected/all, seed configuration, archive/restore and board-local job/error state. Space-drag or the hand tool pans; wheel pans and Ctrl-wheel zooms. Mobile uses an explicit board list and Open action rather than miniature editors.

Only an opened board mounts the existing full Canvas editor. The overview uses visible thumbnails/layout previews; distant cards keep lightweight status/title placeholders. Returning from focus preserves workspace camera, selection and document-local draft/history. Board links use `?app=create&project=…&board=…`; legacy `canvas=<document ID>` links also resolve. Changing boards does not create another chat or microphone engine.

## Ownership and coordinates

`canvas_workspaces` stores project-owned placement JSON and its optimistic-concurrency revision. `moss_boards` wraps one existing `canvas_documents` record, with a unique document owner, metadata revision, archive flag and MOSS settings. Migration: `c27e8b6f495e`, following `b16d7a5e384d`.

Three independent coordinate systems remain separate:

1. World coordinates/card dimensions position boards.
2. Existing artboard dimensions and nested parent-local rectangles describe composition.
3. The focused editor's camera controls presentation inside that board.

Moving/resizing a card changes only the workspace revision. It does not change the document, artboard size or serialized MOSS boxes. Workspace movement/connection undo is separate from each document's region undo. Movement undo preserves boards added after an older action. Cross-device placement conflicts retain the local position draft, offer export/reload and do not block rendering a valid saved board. An incoming layout update cannot silently replace a position while it is being dragged/edited.

Archive is not deletion: documents, assets, pending jobs and pinned source versions remain. Archived boards can be inspected/restored; new generation requires restoration. Archive itself uses explicit Restore rather than deleting assets through Undo.

## Immutable generation and chat targeting

The existing `/projects/{project}/canvases/{document}/generate` route now accepts the explicit board ID/metadata revision. It snapshots document revision, board settings, pinned reference identities, fixed workflow version/hash and resolved seed before preflight. The initial saved-revision/ownership checks remain. Later selection, workspace movement or newer drafts cannot change that accepted snapshot or make it use the newly selected board.

The previous final check against the *current* document revision during preflight was replaced by a check against the actual immutable saved content. The job retains its captured revision and version-selection counter. Completion is auto-displayed only for the latest submitted intent when document revision, board settings revision and explicit result selection still match. Otherwise it remains in history with a new-result indicator. Completion never pans, selects another board or opens a modal.

Prepared graph and workflow-contract digests are checked again by the worker. Disabled/changed contracts, missing workflows and missing pinned assets fail the affected job without losing the document/previous output. Existing legacy Canvas jobs without the new contract-digest field remain compatible with their original graph guard.

Generate saves the target draft first. A failed save retains it. A draft changed during its initial save requires explicit resubmission rather than silently using an unintended older draft. Once generation preparation has captured its saved snapshot, later edits remain independent. The local Preparing state is shared across editor mounts; Queued/Running/Ready/Failed badges come from durable jobs. Transport identity (IDs, revision, seed policy and request key only—no prompts, files or credentials) survives reload in session storage. Retrying an uncertain response returns the same accepted job/seed.

The shared composer shows the selected board. Each send captures that target before awaiting save/preparation; selecting B meanwhile cannot retarget A. The repeatable command **“Generate composition”** (also simple generate/render/run board/image variants) uses the same explicit snapshot endpoint and deterministic message idempotency key, without asking a model to reconstruct a workflow. Arbitrary new image briefs receive guidance to edit the board first; they do not overwrite its prompt. Discussion/explicit asset understanding can still use the existing conversation service, but Canvas-scoped tool calls cannot prepare/upload/queue a different workflow. Other app views and their normal model/workflow paths are unchanged.

## One shared queue

The installed execution path has one tested local GPU slot; no higher-capacity selector or guessed free-VRAM scheduling was added. A shared dispatcher (`worker --canvas-queue`) has a database-specific OS lock. Duplicate wake attempts exit at the guard rather than creating board-owned renderers. All boards/projects in that database share it. Only Canvas jobs and legacy jobs explicitly marked ready by their existing launch path participate; previously unstarted legacy queue entries are not silently drained.

Ready local jobs are ordered FIFO. Capacity is acquired using the existing cross-process GPU lease **before claiming** a job, so waiting work remains Queued in both board and global tray. The provider can re-enter that same thread's lease. Other local Darius workers use the same lease; external ComfyUI queue occupancy is checked before claiming. A persistent dispatcher reads the selected planner configuration for the existing GPU handoff without modifying saved model settings.

Queued cancellation is atomic and scoped to the specified board/job. Running work is not globally interrupted from the workspace. Failed/OOM jobs do not erase other boards or automatically change resolution/settings. Startup/wake reconciles durable queued work; active interrupted jobs stay under the existing recovery mechanism and are not blindly resubmitted. Canvas progress is shown as status rather than an invented elapsed-time percentage in the global tray.

## Pinned visual references—not conditioning

The installed `moss-bboxes-v1` graph remains text-to-image. A connection pins an explicitly chosen completed generation, original asset ID and content hash. The confirmation picker shows the chosen image/version identity. Updating a pin is explicit and confirmed; new source outputs never update it automatically. Removing/updating a connection is undoable and never deletes the image or submits another render.

The target inspector displays the exact pinned thumbnail and labels it **“Visual reference — not sent to MOSS.”** Newer source versions are indicated without substituting them. Archived sources retain usable asset links. Reference ownership/version/job checks are server-side and project-scoped. Frozen reference metadata is stored in the generation's provenance, not misrepresented as a model-conditioned parent image.

Thumbnails use the existing derivative pipeline with a thumbnail-only, cached opt-in. They are reused across refreshes/devices; overview does not repeatedly create full proxies or download original images for distant boards. Existing manual derivative behavior remains unchanged. Originals are loaded when deliberately inspecting an exact version or opening the editor.

## Code and API surface

- `apps/api/darius_api/moss_workspace.py`: workspace/board validation, lazy mapping, metadata, summaries, reference validation and queued cancellation.
- Existing `canvas_api.py`, `services.py`, `worker.py`, `gpu_handoff.py`, `comfy_assistant.py`: immutable task integration and shared capacity; existing queue, trust, ingestion, Library and MOSS compilation are reused.
- `apps/web/src/components/moss-workspace.tsx`: lightweight DOM world/cards, connections, navigation, inspector and focused-editor host; no new rendering dependency.
- `apps/web/src/lib/moss-workspace.ts`, `canvas-intent.ts`: coordinate/persistence helpers, per-document saving and reload-safe request identity.
- Existing `canvas-workspace.tsx`: exported focused editor, shared save registration and board-aware seed/request ownership. Region drawing/serialization was not rebuilt.

Workspace routes are under `/api/v1/projects/{project}/canvas-workspace`: GET, POST `/layout`, POST `/boards`, POST `/boards/{id}` and POST `/boards/{id}/cancel/{job}`. Document/history/select-result/generate routes retain existing IDs. Full OpenAPI was regenerated. Overview queries fetch active/latest/pending receipts rather than loading every historical compiled layout for every distant board.

## Verification evidence

- Backend targeted/regression suite: **310 tests passed**, including 17 workspace tests. Coverage includes migration/reopen, document isolation, placement CAS, independent duplication, edits during preflight, project/version checks, immutable visual notes, queued cancellation/archive retention, message-targeted generation, capacity-before-claim, ready FIFO, contract tampering, missing workflow recovery, generic graph blocking and thumbnail cache reuse. Existing workflow/Block Party, assets, GPU handoff, recovery, reply-stream and conversation regressions are included. Migration round-trip passed.
- Full web suite: **242 tests / 58 files passed**, including new world-coordinate, independent unmounted draft, clean-state reconciliation, request-identity and A-to-B chat-target race checks.
- Typecheck and production build passed. Full ESLint has no errors and the same five existing voice-hook warnings. Existing anyio/dependency and circular-FK migration warnings remain; they were not broadened into unrelated maintenance work.
- Real browser: light/dark desktop (1600 × 1100) and phone (412 × 915), overview without mounted editors, move/undo, independent B/C drafts, focus return and reload. Additional concurrent position-edit check preserves the remote save and retains the local draft until explicit reload. Production-build checks repeat the core flow.
- Reference UI: explicit version thumbnail/identity, target confirmation, intentional update, undo/redo and target pinned preview passed, with **zero** generation requests/cascades.
- **Four real local GPU renders** on the existing ComfyUI 0.42.4 / RTX 5080 installation: A red cube runs; B blue sphere queues under capacity 1; C stays editable/focused. A's second version leaves B's original pin unchanged until explicitly updated. A separate actual UI Generate on C survives browser reload while queued/running: exactly one submission, one job, one result, same board. Existing Library ingestion and declared SaveImage output collection are used.

Reports: `data/multi-board-acceptance/generation-report.json`, `reload-report.json`, `reference-ui-report.json`. Real-test project: `2359acb8-7113-4ed4-b8b7-d941555c9f54` in the isolated acceptance database. The three-board report retains the original pin before the later explicit UI update. Images were visually reviewed: correct red cube/blue sphere subjects appeared; changing the cube box also changed scale/placement, but its second image overshot the requested box. MOSS layout adherence remains advisory, not pixel-perfect. The additional contract/cache/legacy-ready safeguards have targeted tests; initial GPU records predate some of those extra metadata fields and are retained as-is.

Before: `data/screenshots/2026-10-22-canvas/implementation/`.
After: `data/screenshots/2026-10-23-multi-board/` (overview, selected board, focus, real results, pinned-version inspector, active-job reload result).

## Boundaries and deployment

MOSS boards only. One registered compatible adapter is shown honestly; no placeholder model-family selector, I2I/video route, mask/protect-pixels control, independent generated layers, automatic connector execution, cross-project source picker or new vision service was added. One in-flight UI intent per board is supported; intentional further variations are separate requests. Full arbitrary workspace export/import and archive-as-history-undo are not introduced.

The recording named in the handoff was not found under the supplied local assets/screenshots paths; its handoff observations were treated as verification points, not additional source-code evidence.

The initial implementation was verified without deployment, per the handoff. At that stage the live API/web were not restarted and the production migration was not run. Tests used API 8004, dev web 3001 and an isolated production-build preview on 3002, with database/definitions under `data/multi-board-acceptance/`. Only isolated test projects were written. GPU lease scope remained the normal data directory so tests could not overbook the shared GPU. No ComfyUI/voice restart, model download, dependency addition or Block Party repository edit was needed. The original MOSS UI master SHA-256 remains `2077e236a84a8518e4614a35f7cb52b2a1b953da226c51eee02246e89f08ca0d`.

The isolated preview API/web servers and test dispatcher were stopped after verification. Reports, screenshots, generated assets and the acceptance database are retained. Next's temporary preview type-path additions were restored to the original live paths.

Builds used `DARIUS_NEXT_DIST_DIR=.next-moss-build` to avoid replacing the live `.next` artifacts. Its default remains `.next`. When deployment is requested: back up the live database, apply Alembic through `c27e8b6f495e`, build normally with preview environment overrides unset and restart the app's API/web using the existing launcher. Do not point acceptance scripts at the live user database.

## Authorized deployment — 2026-10-23

Deployed after the user requested application of the update. Database backup, integrity check and previous web build are retained under `data/backups/multi-board-20261023-103331/`. Applied `b16d7a5e384d → c27e8b6f495e`; before restarting, verified unchanged row digests for projects, Canvas documents/generations, assets, jobs and model preferences. No active jobs were present during the switch.

Built the normal production `.next` with preview overrides unset, then restarted only the API/web on 8000/3000. Existing ComfyUI, voice and HTTPS gateway processes were retained. A browser smoke check through `https://192.168.50.10:3443` passed: the two existing `tictac` documents mapped to independent boards with original document IDs, overview mounted no region editors, focus/back worked and reload retained both boards. No model calls or renders were submitted by this deployment check. Evidence: `data/multi-board-deployment-report.json` and `data/screenshots/2026-10-23-multi-board/deployed-overview.png`.

### Board movement and image cards follow-up

The entire card now moves its own board in selection mode, including the image, title and copy. Previously only the title strip moved a board. Hand mode, Space-drag and middle-button drag pan the workspace. A four-pixel threshold separates clicking from moving; pointer cancellation discards the move, and pointer capture retains the gesture outside the card. Dragging focuses the stage so workspace shortcuts work immediately. The gesture captures its own board and zoom and commits one independent placement/undo action.

Generated images occupy the card with overlaid title/status/actions. A contained sharp image preserves the full composition; a blurred copy fills mismatched proportions behind it. The fit icon matches a single card to the selected output's actual asset dimensions, falling back to the draft artboard. Existing presentation bounds still apply (280–800 wide, 350–900 high); very extreme ratios retain the contained-image backdrop. Fit is undoable, preserves position and other boards, and does not change the artboard or output. Mobile selected previews use the artboard ratio rather than a fixed-height thumbnail.

Verified 24 targeted web tests, typecheck, scoped ESLint and the production build. `scripts/check-moss-board-cards.cjs` passed against both preview and the deployed LAN HTTPS frontend in light/dark desktop and mobile: independent image dragging at different zooms, stable camera, other boards untouched, undo/redo, pan controls, cancelled drags, double-click focus/back, full-card preview and fitted proportions. Browser tests mock only layout writes and prohibit other mutations/model/render calls. Screenshots: `image-cards-light-1600.png`, `image-cards-dark-1600.png`, `image-cards-light-412.png` in the existing screenshot folder.

Deployed by restarting only web on port 3000. API, ComfyUI, voice and HTTPS gateway processes remained running; no database migration was required. Previous build: `data/backups/moss-cards-20261023-112531/web-next/`.
