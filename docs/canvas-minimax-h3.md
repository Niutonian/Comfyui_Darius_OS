# MiniMax H3 Canvas video boards

## Using it

Create → Canvas → **Video board**. Open it, choose Animate image, Camera direction or Reference video, pin project images and enter the scene/action. Audio direction is compiled visibly into the actual prompt. Generate saves pending video edits first and queues one immutable job. Mode changes/save/playback never generate.

Each mode keeps its own draft and image bindings. All three share board history. Image boards retain their independent documents and history: select an image result in the workspace inspector → **Use in video board** to explicitly pin that asset/version into a new or existing video board. Pinned visual notes remain distinct from conditioning inputs.

## Size and duration

Each mode has independent **Aspect ratio**, **Output resolution** and **Requested duration** controls. The eight Canvas ratios include landscape, portrait, square and ultrawide. Resolution choices are Workflow default and 480p/720p/1080p classes. The dropdown shows the exact final pixel dimensions: the model uses a 32-pixel grid, so a 720p-class landscape render is 1280 × 736, and 1080p-class is 1920 × 1088.

All modes accept integer requests from 5 through 15 seconds at 24 fps, inside the installed node's documented trained frame range. The exact `17k+5` frame count and nominal duration are displayed; a requested 5 seconds gives 124 frames (~5.167s), 8 seconds gives 192 frames, and 15 seconds gives 362 frames (~15.083s). Camera direction now honors its selected duration instead of always using 124 frames. New camera drafts start at 5 seconds. Legacy camera drafts are read with their original 5-second behavior, without rewriting stored data; an explicit new duration choice is saved normally.

Reference mode keeps its two stages. Workflow default preserves the imported 1.5× upscale; an explicitly selected resolution binds the upscaler's supported target-dimensions mode, so its final result matches the displayed dimensions. Its smaller first-pass dimensions are also shown. Camera preprocessing follows the selected output pixel budget, retaining the imported 0.5-MP preprocessing for Workflow default.

Saving or changing controls never generates. Generate freezes the selected dimensions, timing and per-mode draft in the existing immutable job; later edits cannot change a queued job. Older jobs retain their original graph. Larger frames and longer clips use more GPU memory; preset availability is not a VRAM-fit guarantee. No arbitrary FPS or custom pixel sizes are exposed.

Cards support the existing free placement, fit, duplicate and archive controls. Native video controls provide play/pause, seek, mute/volume and fullscreen; downloads retain generated audio. Cards start muted on explicit Play, pause offscreen and do not autoplay across the canvas. The focused viewer uses the existing Board / Chat / History dock and phone sheet. Reloading a board URL reopens Canvas directly.

## Versioned recipes

Original UI files are preserved in `data/handoffs/minimax-h3/originals/` and each profile’s `source.ui.json`. Comfy MCP supplied the initial flattened `source.api.json`; each profile has a checked `template.api.json` and manifest documenting changes and bindings:

- `minimax-h3-animate-image-v1`: supplied FL2VA + LightX2V four-step recipe, shift 12/3, Kitchen attention. Raw model feeds the scheduler; the patched model feeds the guider. Both decoders use denoised output slot 1. Final sink 4. Starting frame only; omitted ending input remains disconnected.
- `minimax-h3-camera-direction-v1`: flattened subgraph with promoted values restored from `widgets_values_named` through the definition’s actual `linkIds`/target sockets. Camera LoRA 0.8; Turbo flag true / LoRA 1 / 8 steps, Base branch 20. Written node-193 prompt is preserved. The original timing-only path resolved to 124 frames/24 fps; the current compiler promotes length from the saved duration. Disconnected trajectory outputs are not exposed as conditioning. Both decoders use output slot 0. Final sink 92.
- `minimax-h3-reference-video-v1`: supplied Singularity / reference LoRA / Sage patch. Virtual routing and bypasses resolved by exporter. Scalar Text becomes an equivalent core string literal. Upscaler schema drift is repaired from named source fields: cuda/fp16, no temporal chunking, current `offload_after_upscale=true` corresponding to imported force-unload. Beta 12 split at 8, video-only 1.5× spatial upscale, original audio latent retained. Final sink 214, intermediate sink 264, one job/history entry.

Working templates contain no usable example filenames. Source files and template identities are checked, concrete seeds are decimal strings at the UI boundary and uint64-safe in storage. Resolution follows the installed core selector (1024² pixels/MP, ties-to-even, multiple 32). Duration uses the runtime’s 17k+5 grid. Actual probed metadata belongs to each output; stage-1 dimensions are not presented as final reference dimensions.

Inputs are explicitly project-authorized, hash/version-pinned images uploaded to loopback ComfyUI input storage. The worker rechecks source ownership and model identity hints. Provenance retains mode/config, exact effective prompt, token/socket/upload mapping, source hashes, original/export/template hashes, model/sampler settings, seed, requested/nominal timing, graph digests, runtime identity and output stage roles. Model fingerprints are size/mtime/first-64-KiB hints, explicitly not full weight checksums.

Uses existing Canvas documents, board revisions, immutable Canvas generations, internal workflow registry, persisted worker and shared GPU lease. No database migration or second scheduler. Retries reuse the request key. Mode switches after queueing cannot mutate the job. Completed videos can display alongside a newer editable draft; explicit History selections and newer generation requests still take priority. Failed stage 2 retains a clearly intermediate video; it never becomes the selected final. Output collection is ordered by the declared sinks for the actual prompt, not latest files.

## Verification (October 24)

Real GPU executions of all three recipes passed, using acceptance images from the earlier size tests (no edits to user projects). Actual MP4 video/audio streams decoded; all output FPS values are 24, and A/V stream durations differ by less than 50 ms:

| Recipe | Actual final | Frames | Actual video duration | Related intermediate |
| --- | --- | --- | --- | --- |
| animate-image | 1376 × 768 | 243 | 10.125000s | — |
| camera-direction | 960 × 544 | 124 | 5.166667s | — |
| reference-video | 1440 × 832 | 243 | 10.125000s | 960 × 544 |

`data/minimax-h3/render-report.json` contains prompt IDs, complete ffprobe metadata, audio decode/volume checks and compiler snapshots. Visual frames were inspected; this does not establish broad motion, identity or audio-quality guarantees.

`ingestion-report.json` separately verifies actual API queue/worker/asset ingestion for each mode by replaying these completed acceptance files, plus an injected stage-2 failure. It does not claim a second fresh GPU run. `ui-report.json` covers desktop/phone, light/dark, mode draft retention, exact input retention, reload, real video playback and stage history without submissions. Screenshots are next to these reports. Targeted backend tests: 106; frontend tests: 253; TypeScript, changed-file lint and production build passed.

The size/duration update has an additional real GPU acceptance run, recorded in the ignored `data/video-controls-acceptance/report.json`. Camera direction rendered 864 × 480 / 192 frames (8 seconds); Reference rendered 480 × 480 / 124 frames, with its 320 × 320 intermediate; Animate image rendered 480 × 864 / 158 frames. Every output matched the compiled dimensions and frame count, with both video and audio streams and A/V durations within 100 ms. This verifies representative 480p-class settings, not GPU memory fit for every larger combination. The update passed 153 targeted backend tests, 19 frontend tests, changed-file lint and the production build. Browser checks covered all three modes at desktop and phone widths, including dimension/timing updates and control sizing; backend tests cover saving, duplication, legacy defaults and the full size matrix.

## Explicit initial limits

Starting image and image-reference conditioning are available. Ending-frame controls, reference motion clips, standalone audio reference clips, soundtrack pairing, trajectory drawing, audio-free derivatives, latent resume and stage-1-only generation are not exposed. Those source branches were bypassed/disconnected and require distinct validated adapters. Roles such as subject/style/environment assist authoring; they are not extra conditioning sockets. Up to nine ordered images are schema-supported; the actual Reference acceptance run used three. Deleting a reference cannot silently reassign Picture tokens. Turbo camera was GPU-tested; Base 20 uses the validated branch but has not had its own separate acceptance render. No arbitrary FPS/resolution or GPU-memory-fit promise.

Generated audio stays in the original video; muted playback does not request silent generation. Audio was decoded and duration-checked, not perceptually graded. The current frame inputs use the installed node’s stretch behavior, disclosed in the UI. Reference max sizing preserves each source aspect and downsizes only.

## Immediate input previews

The viewer and card read the shared board draft, so image selection/removal appears before Save or Generate. Upload image uses the authenticated asset pipeline and binds the returned image/version on completion. The focused viewer displays all current reference images and preserves access to the last generated video through Input images / Generated video controls. Uploading disables Generate until the new binding is ready. Desktop/phone browser acceptance verifies both library selection and a real multipart upload without board saves or render submissions (`input-preview-report.json`).
