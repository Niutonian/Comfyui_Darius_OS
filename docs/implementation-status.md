# Darius implementation status

Last updated: 2026-09-17

## Managed default workflow selection — September 17

- Darius now searches the managed `workflows/defaults` directory before the configured ComfyUI workflow folder. `Darius_*.json` candidates receive priority while custom workflows remain available to power users.
- Default files can be copied and inspected directly, including saved workflows that are not registered with the Comfy MCP library. A conversion failure is reported for that candidate only and does not stop inspection of the remaining candidates.
- Removed the assistant-harness rule that disabled tools after two failed workflow inspections. Hard call, round, and time budgets remain in place.

## Create and Map usability refinement — September 13

- Preserved the updated sage studio, Light table/Stacks layouts, map levels, and territory exploration. Create now defaults to an even asset grid; a featured preview appears only after an explicit Pin to desk action and can be unpinned. Added media-count filters, newest/oldest/name sorting, search clearing/reset, readable filenames, and a direct Create with Darius action. Technical hashes/provider badges were removed from browsing cards; underlying asset details remain available.
- Map now has one level selector, a collapsible contents panel, clearable search, and an explicit Back action. Clicking empty canvas clears selection without unexpectedly leaving a territory. Changing levels clears the previous search. World focuses on the project, characters and scenes; workflows remain available in Tools. Small maps omit the minimap; fit-to-view can accommodate larger graphs. Organize story opens the actual Create story forms.
- Compact composer treatment on Create/Map gives more space to the working area. Mobile layouts use a two-column gallery, compact controls, and responsive map/fullscreen panels. Project changes remount Create state. Reduced-motion preferences are respected.
- Validation: 48 frontend tests passed; lint and TypeScript passed. Read-only Chromium checked filtering, sorting control, pin/unpin, search reset, stacks, contents toggling, map search, territory/back behavior, pane clicks, fullscreen bounds, story-form handoff, and mobile overflow. Review scripts/screenshots are under `.tmp/studio-review/creative-*`, `create-refined*`, and `map-refined*`. No project records or generation jobs were changed.

## Local wake words and OmniVoice — September 12

- Installed isolated `.venv-voice` with local Vosk wake detection, faster-whisper command transcription, and OmniVoice synthesis. Model revisions are pinned and recorded under `data/models`; runtime model loading is offline. The loopback service on port 8002 starts with the normal launcher and warms OmniVoice in the background on CPU.
- Talk uses the local microphone/audio-worklet path and local WAV playback. Composer settings expose **Listen for "Darius" locally**. Supported wake phrases include Darius, Hello Darius, and Hey Darius. Stop/goodbye returns to wake listening; switching off, leaving Talk, or changing projects releases the microphone. Ambient text never reaches the assistant AI; activated commands still use the configured assistant.
- Connected the existing `LocalTtsProvider` to OmniVoice and configured `.env`. Live voice health reports wake and transcription models ready, OmniVoice loaded, and no error; the main API reports TTS ready.
- Validation: 66 backend tests and 42 frontend tests passed; final focused voice tests, lint, TypeScript, and production build passed. Real local synthetic audio tested three wake positives and four unrelated negatives through WebSocket, plus inline Whisper transcription. Chromium exercised a real synthetic microphone, audio worklet, local wake/Whisper recognition, one mocked AI turn, local WAV playback, disarm, and mobile bounds. Real OmniVoice and the app adapter generated WAV files. Warm short-reply synthesis measured 4.13 seconds on CPU; initial cold synthesis took 92 seconds.
- Limits: English, turn-based, Talk must remain open; actual microphone/accent quality needs user testing. OmniVoice weights are non-commercial and its bundled tokenizer license declaration is incomplete, so this remains the replaceable prototype required by the handoff. See [local voice operation and licensing](local-voice.md).

## Visual project context and voice-to-video workflows — September 12

- Added project-scoped asset search by name, ID, or saved generation prompt, and actual image inspection through bounded JPEG previews. PNG/JPEG/WebP originals stay untouched; FFmpeg produces transient previews. Preview bytes are passed as multimodal model input and are not saved in chat metadata. The image input format follows [OpenAI's Images and vision documentation](https://developers.openai.com/api/docs/guides/images-vision). Viewed and bound asset IDs persist in conversation context so subsequent requests can refer to previously discussed images.
- Added workflow discovery ranked by requested provider, output media, reference-image compatibility, and recorded conversion success/failure for unchanged files. Rankings are compatibility hints, not quality claims; graph/schema inspection remains authoritative. Registered workflow IDs can now be inspected as well as saved filenames.
- Added explicit image bindings to workflow preparation. Project media is copied into ComfyUI input storage, the returned upload filename is normalized from the CLI's uploads list, selected loader slots are replaced, and source provenance survives later edits and generation records. New video bindings reject leftover template-image loaders. Inspected optional extra references can be removed from a graph copy for a one-image request.
- Talk now has a project-image picker; gallery and inspector images have Use in conversation. Selected images travel with both voice and typed requests. Visual replies show selectable thumbnails, and review cards retain source assets. Selection clears when projects change. Workflow exploration now has a bounded 165-second backend budget with a 180-second client timeout.
- Verified the installed MiniMax H3 image/reference-conditioning and required utility nodes as built-in local modules and added those specific classes to local-render eligibility. External and unrecognized nodes retain approval requirements.
- Live validation used an isolated project and synthetic green image: real FFmpeg preview; successful configured-model visual recognition; real MCP upload; single-reference MiniMax graph validation and local-node verification. A complete live assistant reply independently viewed the image, discovered/inspected workflows, prepared a five-second MiniMax draft with the single source bound, and stopped before rendering. No video render was submitted. Review artifacts are `.tmp/visual-video-live-1789231330827551200/`.
- Validation: 35 backend assistant/ComfyUI/local-render checks passed; six focused visual checks also passed after the final conversion-cache refinement. Existing 35 frontend tests plus three new reference-picker tests passed. Lint, TypeScript, and production build passed. Chromium with mocked speech/API writes verified reference selection in a spoken request, visual response thumbnails, removal/reselection, and mobile layout without horizontal overflow. Screenshots: `.tmp/studio-review/visual-references-*.png`.
- A seventh focused check confirmed that a new video binding cannot retain an unbound template-reference loader. The idle production worker was reloaded. Installed-template conversion history was refreshed: the Larryvrh Turbo I2V template returns an empty MCP conversion response and ranks below the working MiniMax reference-to-video template.

## Failed generation investigation — September 12

- Investigated `f081762e`, `f546978c`, `bb2a2242`, and the preceding failure `1abb0955`. The first three failed before rendering with `KeyError: '30:16.sampling_mode'`. API graph inputs such as `sampling_mode.temperature` contain literal dots; splitting their slot at the last dot incorrectly treated part of the input name as a node ID.
- Added graph-aware slot resolution shared by draft editing and execution. It preserves exact node IDs and input names, including dots and subgraph colons, and rejects unknown or ambiguous addresses. Regression coverage includes both copied-workflow edits and execution while preserving originals.
- Replayed the exact saved parameters from all three Krea jobs onto isolated copies and passed live Comfy MCP validation without submitting renders. The older H3 job recorded an unparseable MCP response; its raw response was not saved, so its historical cause cannot be established. Current live H3 conversion and envelope parsing passed.
- Restarted the existing idle worker to load the fix. Failed jobs and their history remain unchanged; no production renders were requeued. Review copies are in `.tmp/failed-generation-check-1789225526520665100/`.
- Validation: 32 tests passed across workflow editing/execution, local-render authorization, worker execution, and recovery. The OpenAPI contract remains current; the replacement worker started without errors.

## Voice and chat local rendering permission — September 12

- Added a server-persisted **Allow local rendering** control per project. With it enabled, voice and typed requests can prepare a graph and use `queue_local_render` without another approval. `job_status` reads jobs in the active project; chat links queued jobs to the inspector and job tray. The assistant cannot change the permission.
- Automatic execution accepts only loopback ComfyUI, enumerated built-in node classes with matching installed module origins, and workflows without an external cost. Unknown custom and API nodes remain on the manual Review generation path. Node metadata is fetched only for required classes to avoid expensive full-registry discovery.
- Queueing creates the action plan, approval history, generation record, and message/job association in one transaction. Reply retries reuse the existing job, including after worker-launch failures. Each subprocess worker claims only its assigned job; it does not drain unrelated queued work. The graph snapshot hash, permission, and installed node origins are checked again before execution, and final graph validation must explicitly succeed before submission.
- Added an additive permission-table migration and applied it to the local installation. Disabling permission prevents not-yet-started automatic jobs from executing; already executing renders continue.
- Validation: all 35 frontend tests, lint, TypeScript, and production build passed. Chromium with mocked speech and API writes verified toggle persistence/revocation, voice input, spoken queue confirmation, job access without another approval, and mobile bounds. A real isolated ComfyUI smoke rendered a 64px blank image, automatically started its scoped worker, ingested its asset, and confirmed repeat queue requests reuse the same job. No AI or paid nodes were involved. Browser artifacts are `.tmp/studio-review/local-render-*.png`.
- Live AI interpretation of spoken requests still depends on the configured model/service. Arbitrary custom-node workflows do not receive automatic approval.
- Final backend verification: 26 focused checks passed, including all local-render and ComfyUI regressions, the updated 37-path API contract, and migration round-trip/schema integrity. The broader suite's only failure was its old 36-path assertion; the corrected assertion passed in the final run. Final permission UI tests, lint, and TypeScript also passed.

## ComfyUI conversation tools — September 12 follow-up

- Resumed the conversation tool integration: live workflow/node/model inspection, project asset upload, copied workflow overrides, API graph validation, and persistent draft registration feed the existing Review generation flow. Prepared graph defaults are preserved, and workers can discover newly registered drafts after startup.
- Hardened draft preparation to reject malformed node structures before calling ComfyUI and to require an explicit positive validation result before registering a draft. Added seven regression cases for malformed nodes and missing, null, or incorrectly typed validation results.
- Verification: the existing 25-test backend suite passed; all 11 focused ComfyUI tests passed after the validation changes. The OpenAPI contract is current. All 33 frontend tests passed using `npm test -- --pool=threads --maxWorkers=1`; default fork workers timed out during startup on this Windows environment. ESLint passed.
- Production build and TypeScript checks passed. Tests use isolated data and mocked providers. Successful live AI tool use and real rendering were not verified in this follow-up.

## Full-size asset previews — September 12

- Gallery image/thumbnail clicks now open a dedicated near-fullscreen media dialog. The gallery's separate details button retains access to the inspector. Inspector and map detail previews expose a visible Full size control; clicking their image also expands it.
- Image viewing supports Fit to window and Actual size (100%) with scrollable original pixels. Video/audio use native playback controls. Media uses the existing path-safe original content endpoint. Loading and media errors are visible; closing unmounts playback content.
- Native dialogs provide focus containment and close controls. Escape closes only the asset viewer, preserving the inspector or underlying expanded map, and focus returns to the preview trigger.
- Verified production build/TypeScript and lint. Read-only Chromium verified gallery/inspector access, actual rendered width matching natural image width, fit mode, nested map preview closing, Escape preserving underlying panels, and mobile dialog bounds without overflow or page errors. No asset data was changed.

## Individual map arrangement and minimal home — September 12

- Enabled independent card dragging with controlled position updates. Only the released card's position is persisted; saved coordinates are scoped by project and stored in browser localStorage, independently of server creative data. Arrangements survive mode changes, expanded mode, and page reloads. New nodes still receive an automatic starting position.
- Removed the welcome headline and its subtitle. Moved the creative-space caption beneath the Darius/os wordmark and centered Generation/Workflows immediately beneath the desktop header, with a compact mobile arrangement.
- Added a small, eased mouse parallax to the three background shapes at different depths. Reduced motion disables the effect; animation frames and listeners are cleaned up, and hidden-tab motion is reset.
- Validation: 27 tests passed, including project-isolated map-position persistence. Browser checks confirmed only the dragged node moves, other coordinates stay unchanged, saved positions survive expansion/reload, removed text is absent, header/control placement is correct, parallax responds to mouse movement and stops for reduced motion, and the mobile layout has no horizontal overflow. Browser verification used a separate context without server mutations.

## Story map redesign — September 12

- Replaced circular labels with typed cards containing readable titles, status, context, and available image/video previews. Character cards use approved image references when available. Generated UUID filenames get shorter display labels; originals remain in details.
- Added a searchable contents directory, Overview/Characters/Scenes/Media/Tools layers, click-to-focus search results, highlighted selection connections, an integrated preview/details panel, and navigation between related entities. Organize story opens Create. Map entry closes a previously open global inspector.
- Connections distinguish project membership, approved character references, scene media, media derivation, and available generation tools. Tools are not shown as the producer of assets without provenance evidence. Removed the old six-asset/four-workflow display caps; all assets supplied by the existing project query (up to 500) can appear. Positions remain automatically arranged and are not editable/persisted.
- Added native modal expanded mode with exact 100px desktop insets. Search, layers, map and detail controls stay inside the modal. Escape and restore controls close it; native dialog behavior contains keyboard focus. Small screens and very short windows use 16px insets.
- Verification: **25 tests across 10 files passed**, ESLint passed, production build and TypeScript passed. New graph tests verify references beyond the old asset limit, scene links, and lineage without dangling edges. Read-only Chromium checks against the user's running project verified search/selection, exact desktop modal bounds, repeated expand/restore, Escape, mobile sizing without dialog overflow, and no page errors. No project data or generation state was mutated.

## Liquid presence and composer focus — September 12

- Replaced the CSS sphere with an SVG liquid presence: five droplets merge through a filtered mask, separate in response to the pointer, and return with damped attraction. Idle motion gently changes the silhouette. Animation stops in hidden tabs and respects live reduced-motion preferences; listeners and animation frames are cleaned up on navigation.
- Removed the textarea's rectangular focus outline. Focus is indicated by a soft highlight around the rounded composer; an explicit gap separates the text field from the send controls. Keyboard focus indicators on buttons remain intact.
- Verified lint and the production build including TypeScript. Chromium with mocked API responses verified pointer separation, reassembly after pointer leave, reduced-motion stability, absence of the textarea outline, non-overlapping send controls, and no page errors. No provider operations or project mutations were performed.

## Navigation duplication fix — September 12

- Reproduced the reported duplicate home content: `TalkView` and `Composer` were siblings using the same active-project React key. Changing projects could leave orphaned home views in the DOM across subsequent mode changes. Both keys now include distinct component prefixes.
- Removed the two decorative rings around the welcome orb as requested in the annotated screenshot.
- Added shell regression tests covering repeated navigation across three project selections, a single active view/composer, and every restored mode without React key warnings. Before the fix, the test found three page bodies and duplicate-key errors; after the fix it passes.
- Validation: **9 Vitest files / 23 tests passed**, ESLint passed, and production build including TypeScript passed. A separate Chromium context on the running development server used mocked API responses and persisted project selections to exercise three project switches, twelve desktop mode transitions with reloads, and four mobile mode transitions. Exactly one page remained mounted, orb rings were absent, and no console or page errors were recorded. No production project data was changed.
- Existing browser tabs need a full reload once to clear DOM elements already orphaned by the old duplicate keys. The user's running development server was left running.

## Studio refinement — September 11

Implemented against the user's paper layout and ranked visual references, prioritizing the `one` sage/glass references:

- Light sage surfaces, organic animated presence, subdued lime accents, translucent composer, and floating four-space navigation. Animation respects reduced motion; UI needs no remote fonts or image requests.
- Welcome screen with a direct project entry point. Existing workflow planning, media upload/capture, approval, job tracking, and timeline functions remain connected to the existing API.
- Workflow selections now survive prompt submission instead of always being replaced by intent routing. Draft proposals are scoped to their project to prevent showing another project's pending request.
- Production forms are progressively disclosed in Create, leaving the asset library as its primary surface.
- Inspector opens when selecting content and can close with Escape. The map uses circular nodes and reads actual characters, scenes, and approved character reference relationships. Details show saved prompts, continuity, and screenplay information. Newly loaded entities trigger viewport fitting. Positions are automatically arranged; manual node dragging is disabled because positions are not persisted. The existing overview limit of six assets and four workflows remains.
- Map requests expose loading and failure states. Existing project data, workflow contracts, backend provider adapters, and originals were not rewritten.

Validation: ESLint passed; TypeScript passed through the production build; Vitest **8 files / 18 tests passed**; Next.js production build passed. A real headless Chromium flow against a separate SQLite review database passed project creation, explicit workflow selection, saved action-plan creation (without approval/execution), all four spaces, saved character/scene map loading and character inspection, and a 390 × 844 mobile viewport without horizontal overflow or uncaught browser errors. Screenshots remain local in ignored `docs/ui-review/` and are not included in source releases. The first browser pass exposed async map nodes outside the viewport; remounting/fitting when node membership changes fixed the issue and the final browser run passed.

Limits: this is an interface and navigation refinement, not completion of the full film acceptance test below. Realtime AI dialogue, speech transcription, an embedded ComfyUI editor, and real hardware capture/provider execution were not added or verified. No generation worker was started and no paid generation/planning requests were sent. The next task is creative review of the running studio, followed by the existing integration acceptance sequence.

## Current milestone

The second-pass local MVP foundation is integrated. Structured creative data, conversations, inspectable action plans, approval-gated jobs, immutable media and provenance, derivatives and media analysis, versioned timeline editing, OTIO export, and worker-only FFmpeg rendering are implemented behind a FastAPI/SQLite API and a responsive Next.js interface.

This is not yet a completed 30–60 second film acceptance run. Automated validation deliberately uses fake or injected providers and never invokes paid OpenAI/BFL APIs or the real Comfy MiniMax H3 workflow.

## Implemented

### Backend

- FastAPI API with 34 OpenAPI paths for health, projects, characters, scenes, shots, workflows, action plans/transitions, jobs, uploads/assets/provenance, webcam capture, media derivatives/analysis, conversations/messages/explicit planning, events, and timelines/versions/OTIO/render proposals.
- SQLite/WAL persistence for normalized project state, immutable assets, generation records, events, action-plan history, and timeline versions.
- Initial Alembic migration covering the current metadata schema; both upgrade-to-head and downgrade/upgrade drift checks are tested.
- Versioned semantic workflow contracts for local Krea 2 Turbo text-to-image and MiniMax H3 text-to-video; internal Comfy node slots are not exposed to API clients. Prompt intent routing now defaults ambiguous/still requests to image and reserves H3 for explicit video or motion requests. All ten MCP-prefixed user workflows are inventoried in `docs/mcp-workflow-audit.md`.
- Separate worker with atomic claim, restart recovery, retry/cancel behavior, provider output ingestion, hashing, ffprobe metadata, and explicit mocked-provider provenance.
- Replaceable OpenAI planning, BFL, local TTS, and local transcription boundaries. Message creation never plans implicitly; planning and provider execution require explicit routes/actions.
- Upload allow-list, size limit, root containment, UUID filenames, cleanup on failure, and immutable import provenance.
- Immutable image/video thumbnails and browser proxies with graceful per-derivative failure; webcam capture reuses upload persistence and triggers derivatives.
- Argument-safe ffmpeg/ffprobe media analysis for silence, black, freeze, and scene facts, persisted in asset metadata and project events.
- Validated timeline tracks/clips, deterministic shot assembly, immutable edit versions, OTIO JSON export, and explicit-approval render queueing. FFmpeg rendering runs only in the separate worker and ingests an immutable render asset.
- Localhost CORS via `DARIUS_CORS_ORIGINS`; the normal web setup uses a same-origin Next.js rewrite.

### Frontend

- Next.js/React/TypeScript shell with Talk, Create, Map, and Edit modes; project selector, inspector, composer, health status, and job tray.
- Typed wrappers aligned to every OpenAPI JSON/multipart route, including webcam capture, derivatives, media analysis, explicit conversation planning, OTIO export, and timeline rendering.
- Composer file/audio/webcam staging with XHR byte progress, local review, retry/remove/retake, send blocking while uploads are incomplete, immutable asset association, and webcam derivative generation.
- Persisted character, scene, and shot creation with reference/selected-asset association.
- Talk separates action-plan proposal from explicit approval and displays provider, state, identifier, cost, and associated media.
- Edit creates/selects timelines, proposes assemblies, persists trim/reorder/mute/delete changes and edit summaries as immutable versions, downloads OTIO JSON, and creates an accepted version before explicitly queueing a worker-only render.
- Safe metadata-backed media presentation and immutable lineage/generation/provider inspection. Private filesystem paths are never used directly as browser media URLs.
- Responsive and accessibility-preserving navigation, controls, and reduced-motion styling.

### Shared contract and local operations

- FastAPI OpenAPI source of truth committed at `docs/openapi/darius-api.json`.
- `scripts/export_openapi.py` regenerates the artifact; `--check` and pytest both detect drift.
- `scripts/start-local.ps1` launches API and web; the generation/render worker is opt-in with `-WithWorker`.
- Root and web ignore rules cover local environments, provider configuration, databases, Python caches, Node dependencies, Next.js output, TypeScript build metadata, logs, and coverage output.
- Root `.env.example` contains blank provider-key placeholders. Credential-copy scanning confirmed the configured `OPENAI_API_KEY` and `BFL_API_KEY` values occur nowhere outside the ignored local `.env`; there is no evidence that those credentials were exposed by checked-in files.

## Request feedback and draft handoff — 2026-09-14

Inspected the saved pizza conversation: it prepared a draft but created no job. The new Cybertech project had no standing local-render permission, while the older project did. Fixed a workflow-history query referencing a comprehension variable before binding, which broke the assistant reply endpoint. Added persistent elapsed-time feedback, recovery of saved replies after transport timeouts, explicit unrendered-draft labels, and inline job/output previews. Review generation closes the job tray and scrolls to the proposal; guided review no longer buries the form below all workflows. Explicitly approved local plans launch a worker scoped to their job; launch failure leaves a visible queued status. No historical request was automatically submitted.

Validation: 16 assistant/local-render tests and 48 frontend tests passed; production build passed. No new model generation or manual browser acceptance was performed in this fix.

## LangGraph migration — 2026-09-14

Added pinned LangGraph and SQLite checkpoint dependencies. Conversational assistant requests use separate checkpointed model/tool/verification nodes keyed by project and user message. Task milestones persist in message metadata and events; references survive retries. Worker ingestion records task completion/failure. Fixed the event-stream first-500-event ceiling and reconnect cursor handling. Existing Manual/Full auto permissions and message-scoped queue deduplication remain active. Added mocked end-to-end image-to-video, checkpoint failure/recovery and project isolation tests. Details and remaining limits: [agent-harness.md](agent-harness.md).

## Integration validation

Verified on 2026-09-11 without a generation worker or external model calls:

- Fresh temporary SQLite database: `alembic upgrade head` reached revision `879a97ae7905 (head)` and the temporary database was removed.
- Full backend `pytest`: **16 passed** in 3.64 seconds. Two non-failing warnings remain: Starlette's deprecated anyio alias and SQLAlchemy's table-sort warning for the intentional `assets`/`shots` foreign-key cycle during migration test teardown.
- OpenAPI drift check: current at **34 paths**; all implemented media/planning/OTIO/render routes are included.
- Frontend ESLint: passed.
- Frontend TypeScript check: passed.
- Frontend Vitest: **5 files, 12 tests passed**.
- Next.js production build: passed; static `/` and `/_not-found` routes emitted. Node printed a non-failing experimental `localStorage` warning during page-data collection.
- Isolated no-worker HTTP smoke: FastAPI health **200**, Next.js page **200**, and same-origin Next.js-to-FastAPI health proxy **200** with database readiness true. Both process trees and temporary data were removed afterward.

The backend suite covers migration round trips/schema drift, derivative success and graceful fallback, webcam persistence/events, argument-safe analysis, timeline validation/OTIO/approval-gated worker rendering, explicit dependency-injected planning, workflow validation, queue recovery/cancellation/retry, immutable ingestion/provenance, and a no-paid-call structured E2E. The frontend suite covers transport progress/error behavior, semantic asset mapping, composer review, navigation, persisted timeline edits, and explicit render approval.

## Remaining MVP acceptance blockers

Only environment- or approval-dependent acceptance work remains:

1. **Real local generation and duration:** no Darius-triggered MiniMax H3 job has been run. A representative generation can consume substantial VRAM and many minutes, so it requires a deliberately selected short script, explicit approval, available compatible GPU/ComfyUI/MCP runtime, and monitoring.
2. **Paid cloud providers:** BFL generation has not been called. A minimal OpenAI assistant greeting was attempted on 2026-09-12 and rejected with HTTP 429; no successful live assistant response has been verified. End-to-end acceptance requires valid external credentials, network access, billing/cost approval, and intentional paid requests.
3. **Local speech models:** TTS and transcription boundaries exist, but acceptance requires suitable model runtimes/files to be installed, licensed, configured, and exercised on the target machine.
4. **Browser hardware permissions:** real microphone/webcam acceptance requires compatible physical devices, browser support, and a user granting permissions; automated tests cannot grant permissions or assess capture quality.
5. **Final film review:** producing and reviewing a complete 30–60 second scene depends on the approved long-running generation above, sufficient generated source media, local render time, and human creative/quality review.

## Next acceptance sequence

1. Start API/web without a worker and manually verify microphone/webcam permissions and capture quality in the target browser.
2. Install/configure the chosen local transcription and TTS runtimes, then run short non-production samples.
3. Choose one short H3 script and explicitly approve a monitored local generation with the worker enabled.
4. Assemble/accept the generated shots, export OTIO, explicitly queue the FFmpeg render, and review one 30–60 second output with its provenance.
5. Optionally validate OpenAI/BFL only after credentials, network use, and spend are explicitly approved.


## Conversational assistant — 2026-09-12

- Added a structured OpenAI Responses conversational path, project context and bounded recent history, persisted natural-language replies, and optional generation suggestions restricted to registered workflows.
- Reply retries reuse the saved user message and return the existing assistant reply when complete. Lock stripes serialize reply requests in the local single-process API; this is not a distributed multi-worker idempotency guarantee. Attachments must belong to the conversation project. No chat reply queues a job.
- Added a saved project conversation UI, visible voice controls and transcripts, browser speech recognition/synthesis, hands-free turn progression, interruption, and cleanup on stop/navigation/project changes. Recorded media attachments remain separate.
- Refreshed OpenAPI contract to 36 paths. Automated tests cover contextual replies, retry, invalid workflow rejection, no-job behavior, structured provider requests, quota errors, spoken replies, repeated recognition results, microphone denial, and late responses after stopping.
- Chromium smoke used mocked conversation and speech APIs: retry without duplicate prompt, history restored on refresh, listening/thinking/speaking loop, navigation, and mobile overflow passed. Desktop/mobile screenshots are in `.tmp/studio-review/assistant-*.png`.
- Live configured-model access check returned 200. Minimal synthetic greeting requests returned HTTP 429; the account is currently rate limited. No project context was sent in these checks. Real microphone quality and successful live AI speech remain unverified; browser voice requires user permission and a compatible speech service.

Final verification: backend 21 tests passed; frontend 30 tests in 12 files passed; ESLint and production build passed. The running local API exposes the assistant reply endpoint. Chromium regression passed after final refinements.


Voice reply stall follow-up: bounded conversation-save requests (20s) and assistant replies (75s), with request abort and preserved retry input. Voice failures now exit thinking with an explicit error, and errors/retry controls remain in the sticky voice bar. Slow requests show a waiting explanation. Frontend tests: 32 passed; lint, production build, and mocked Chromium voice/retry checks passed. A fresh synthetic live provider check returned HTTP 429 in 0.5s; live replies remain blocked by the provider limit.
