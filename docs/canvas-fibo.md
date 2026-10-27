# FIBO Canvas profiles

**ComfyUI parity verified:** the successful saved ComfyUI example was reproduced through Darius with identical decoded RGB pixels. The separate flat-rectangle benchmark still shows weak FIBO adherence (13–16%, versus MOSS ~98%), but does not prove a transport defect or that a different compiler is required for the working example. See [the corrected spatial investigation](fibo-layout-regression.md).

Open **Create → Canvas → Add FIBO board**. New boards are empty. Select a board and choose **Workflow → FIBO**, then **Fast preview · Turbo · experimental** or **Dev render**. The focused editor exposes the same settings under Generation settings. Switching workflows preserves the neutral layout and remembers each profile's seed; no preset, history selection, pan or edit queues a render.

As explicitly requested, **Fast preview** now uses `fibo2_edit_turbo_int8_convrot.safetensors`, four steps / CFG 1, in profile `fibo-fast-turbo-v2`. A real render and a full queue/worker/asset-ingestion run verified this installed weight with the supplied text-only chain. The checkpoint is officially Edit Turbo, so this text-to-image use remains labelled experimental. **Dev render** independently uses `fibo2_dev_int8_convrot.safetensors`, 30 steps / CFG 5. Both retain `qwen3vl_4b_bf16.safetensors` (CLIP type `fibo2`), `flux2-vae.safetensors`, the selected shared MOSS artboard resolution, batch one, euler/simple/denoise 1 and an empty negative prompt.

Legacy `fibo-fast-experimental-v1` artifacts and historical generations still identify their original Dev weights. Migration `e49a0d816b70` changes existing boards' future fast selection to the new Turbo profile, incrementing the settings revision without changing document revisions or old jobs/results. Promotion from either fast version to Dev retains the same saved composition, prompt and concrete seed.

The supplied prompt is a freeform instruction plus stringified layout elements, **not a native VGL compiler**. Region boxes guide composition; they do not constrain pixels or guarantee exact placement. The real left/right cube tests reached the encoder with the correct changed TLBR coordinates, but the cubes remained broadly centered. The four-step result also showed distorted geometry. The Dev mixed fixture produced a clean blue teapot and legible “TEA TIME” lettering, but text and objects were not rigidly confined to their boxes. This limitation is recorded rather than hidden by a different compiler or prompt enhancer.

## Saved preview → Dev

In History, choose **Render this preview with Dev** on a completed fast result. It uses that result's exact saved document revision, compiled conditioning string, empty negative prompt, resolution and concrete seed. It does not save or read the newer draft as generation input, nor use the preview pixels, mask or latent. The source generation is linked by immutable ID. Selecting its completed Dev result exposes **Compare with preview**, with explicit Preview / Dev buttons displaying the two actual assets.

The same layout and seed can produce different pictures when steps/CFG change. The previous image and newer draft remain intact. Normal Generate uses the current saved draft. Failed, cross-project, cross-board, missing-image, unverified-prompt, missing-snapshot or incompatible-compiler sources cannot be promoted. Repeated transport retries retain one idempotency key. After a terminal Dev job, **Render another Dev version** is an explicit new request.

## Source audit and adapter

Original UI files in `workflows/defaults/` are preserved byte for byte:

| Original | SHA-256 |
| --- | --- |
| `Fibo2_t2i_layout_boxes_turbo.json` | `3e0dd917af509f3558d3349fd4d84cfcb55dad6b5d21ba5709761745b055daa1` |
| `Darius_Fibo2_t2i_layout_boxes_dev.json` | `aa6de8298e5051eff7744729ad6e45d648844a9ee88de5abcb63bdd8f756eef1` |

Versioned artifacts live under `workflows/canvas/fibo-fast-turbo-v2/`, legacy `fibo-fast-experimental-v1/` and `fibo-dev-v1/`: untouched API conversions from the existing Comfy MCP importer, working API templates, structured prompt templates and pinned manifests. Working copies remove only the disconnected UNET loader, correct sampler titles and add core PreviewAny node 28 connected to the same string as TextEncodeFibo2. Node 17's guide preview remains disconnected from the model. SaveImage 24 (fast) / 8 (Dev) are the only collected output sinks.

Compiler `fibo-layout-string-v1` recursively resolves parent-local rectangles, excludes structural/hidden descendants, preserves deterministic tree order and maps characters to ordinary object elements. It preserves exact text, descriptions and up to five six-digit hex palette colours. MOSS explicitly rejects visible palette fields it does not support. CreateBoundingBoxes emits normalized integer `[top,left,bottom,right]`, using Python ties-to-even rounding. KJ SomethingToString joins Python `str(dict)` values with comma-space and no outer array brackets; JoinStrings appends them after the fixed instructions and scene slot. The compiler reproduces this exact installed behavior and the worker verifies the real node-28 receipt against the saved string before ingesting outputs.

The CLI incorrectly flags FIBO's zero-image autogrow input. The existing Qwen compatibility filter now also handles TextEncodeFibo2, and only waives that exact error after proving `template.min=0` against the live local schema. Missing inputs, unknown models, incompatible dimensions and all other errors remain blocking.

Profiles/manifests/templates are hash-pinned. Provenance retains the document snapshot, source UI/API digests, template/compiler versions, exact conditioning bytes/hash, negative prompt, boxes/elements/index map, concrete decimal seed, sampler/model settings, composition-input hash, execution-profile hash, prepared/submitted graph hashes, prompt ID and runtime identity. Model identity hints use file size, mtime and SHA-256 of the first 64 KiB, clearly labelled **not full weight checksums**. The local runtime checkout commit and relevant source-file hashes are retained. A changed available model fingerprint or checkout between approval and execution blocks the queued job. Jobs keep using the existing shared GPU lease, FIFO dispatcher, approval/validation and asset ingestion.

Unsigned 64-bit seeds are decimal strings at the FIBO/browser boundary. Both Canvas and general generation-record seed columns use decimal text storage with integer semantics in Python. Migration `d38f9c705a6f` converts existing integer seeds losslessly. Run `.venv/Scripts/python.exe -m alembic upgrade head` when applying this version to an existing database. MOSS still enforces its original 32-bit range and numeric responses. A rollback is refused if it would lose an unsigned seed.

## Verification (23 October 2026)

Real ComfyUI 0.42.0 / RTX 5080 16 GB; no cloud model calls or model downloads. Isolated database/project, no user document edits. Six actual images were collected, exactly one per declared final SaveImage sink:

| Run | Worker start → completion |
| --- | --- |
| Fast left | 10.60 s |
| Dev promoted from left preview, after draft moved right | 19.40 s |
| Fast right | 5.95 s |
| Standalone Dev, nested object + text + palette | 26.41 s |
| MOSS in mixed queue | 18.46 s |
| FIBO in mixed queue | 10.04 s |

These are observed local durations including validation/ingestion, not performance guarantees. The Dev and source-preview composition hashes/prompt bytes match; the later draft remains revision 2. Every FIBO prompt receipt matched. The installed serializer functions were also executed directly against square, nonsquare, Unicode/quotes/newlines and palette fixtures. Browser checks cover 1440 desktop / 412 phone, light/dark, profile/seed persistence, no automatic render on navigation/settings/history, and real Preview/Dev comparison with no horizontal page overflow.

Artifacts: `data/fibo-integration/acceptance-report.json`, `serializer-proof.json`, and `data/screenshots/2026-10-23-fibo/`. Opt-in rerunnable scripts: `scripts/check-fibo-canvas.py --run`, `scripts/check-fibo-ui.cjs`. They target isolated loopback API 8004; GPU runs retain request identities across reruns. The UI check intercepts generation submissions as a guard; it never claims these browser checks are additional real renders. Backend tests exercise snapshot rejection, standalone Dev, exact old-revision promotion, max unsigned seeds and idempotency.

The [official Comfy-Org FIBO model repository](https://huggingface.co/Comfy-Org/Fibo-2.0) identifies the checkpoint license as CC-BY-NC 4.0; commercial use requires the applicable Bria agreement. The [official Edit Turbo model card](https://huggingface.co/briaai/Fibo-2.0-edit-turbo) describes a separate editing model. No license is changed or model variant silently substituted here.

## Exact ComfyUI reproduction and example import correction

The manually submitted prompt `99aff5de-93ed-4c8e-8f29-3015f173af8d` was reconstructed as a neutral Canvas document with its exact scene, boxes, palettes and seed 64. Darius produced RGB SHA-256 `0a54c265db24bbb840f8525024d95943b740a0be5f9d18608e59f80ea2e289f7`, identical to the existing ComfyUI output. No extra mask/layout step was found on that active path. Some recent Darius inputs have an empty overall scene; these are not equivalent to the rich original scene prompt. This is not proof that scene text alone explains every failing composition.

The CLI conversion did drop the source's V3 BoundingBoxes editor widget when making `source.api.json`. The live compiler rebinds board boxes, so this was not dropping live Canvas geometry. It did make **Load supplied example** empty. That action now reads named `editor_state` from an immutable, hash-verified `source.ui.json` snapshot, restoring the original two regions and palettes. Blank new boards remain blank.

Additional proof: `data/fibo-layout-debug/manual-pixel-comparison.json`, `manual-reproduction-result.json`, `turbo-weight-result.json`, and `turbo-acceptance/result.json`.

## Shared artboard sizes — October 24

FIBO Turbo and Dev expose all eight MOSS presets, from square through portrait, landscape and ultrawide. Both layout encoding and the generated latent use the saved artboard dimensions. Regions retain normalized coordinates when resized. Preview-to-Dev promotion retains the preview’s historical size even after the draft changes. Existing square generations remain reproducible.

Verified with 84 backend tests, 252 frontend tests, TypeScript, changed-component lint, a production build, desktop/mobile browser saves, and ten real ComfyUI renders (eight Turbo sizes plus Dev portrait and landscape). Actual PNG dimensions and prompt receipts matched every request. Artifacts: `data/fibo-resolutions/report.json` and `ui-report.json`.
