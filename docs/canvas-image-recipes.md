# Default image workflows as Canvas boards

## Use

Create → Canvas → **Image board**, then select **FLUX 3 Klein**, **Krea 2 Turbo**, **Qwen Image 2.1** or **Qwen Image 2.1 · Edit**. Create several independent boards or switch workflows inside one Image board: each keeps its own prompt, seed, sizing and settings. All results remain in one labeled history.

Enter a prompt; Generate saves the pending draft and captures the selected workflow/seed before queueing. No render starts on create, switch, upload, save, drag, history selection or duplicate. Qwen Edit pins exact project image versions with stable `<image1>`…`<image10>` labels. Image 1 defines the source canvas unless Custom output is chosen. Library selection and uploads preview immediately. Existing results remain available while the draft changes. Image-result previews support wheel zoom, hand drag and Fit; the normal dock provides Board / Chat / History, with the established phone sheet.

Qwen supports native 4 MP output (2048×2048 square). Krea exposes the imported optional style LoRA and style cue. FLUX/Krea expose their source workflows’ local prompt enhancement, enabled by default and explicitly switchable. History records the actual resulting encoder prompt, separately from the editable original. Krea uses zeroed negative conditioning; other workflows expose a negative prompt with the CFG-1 limitation explained. The image board can explicitly create a Video board from its selected result without generating automatically.

## Sources and graph audit

The four default UI files were copied byte-for-byte into versioned directories under `workflows/canvas/`; originals remain unchanged. Each directory contains `source.ui.json`, the Comfy MCP flattened `source.api.json`, the pinned working `template.api.json`, a pinned manifest and `graph-diff.json`. `data/image-boards/audit.json` verifies original hashes.

| Profile | Original default file | Effective imported defaults |
| --- | --- | --- |
| `flux3-klein-t2i-v1` | `Darius_image_flux3_klein_t2i.json` | FLUX Klein base INT8, 50 steps, CFG 3.5, euler/simple, local enhancement on, portrait 2:3 / 1 MP |
| `krea2-turbo-t2i-v1` | `Darius_image_krea2_turbo_t2i.json` | Krea Turbo FP8, 8 steps, CFG 1, euler/simple, enhancement on with thinking off; optional Darkbrush LoRA off |
| `qwen21-t2i-v1` | `darius_image_qwen_image_2_1_t2i.json` | Qwen 2.1 INT8, 25 steps, CFG 1, euler/simple, no references, PNG output |
| `qwen21-edit-v1` | `darius_image_qwen_image_2_1_image_edit.json` | Qwen 2.1 INT8, 25 steps, CFG 1, source sizing (`resolution=0`), auto/default cache, two reference sockets generalized to explicit optional references |

Promoted subgraph settings are restored through named instance widgets and actual definition link IDs/target sockets. No widget-array position guessing. This repairs lost FLUX sampler/negative/enhancement settings, Krea thinking, Qwen prompts/seeds and Edit reference resolution. Connected resolution routes remain authoritative. Original example subjects and filenames are removed from working inputs; system instructions remain intact.

FLUX’s disconnected box/preview branch is omitted from the working recipe; its source output never reached generation. These boards therefore expose text/image inputs, not invented region conditioning. MOSS/FIBO remain the region-composition boards.

The compiler patches allowlisted inputs only, resolves known boolean switches and prunes branches that cannot execute. Disabling enhancement removes its text-generation branch; disabling Krea style removes the LoRA branch, avoiding irrelevant model requirements. A PreviewAny receipt lies on the actual encoder string path, including enhancement/style. Raw prompt identity is enforced when enhancement is disabled; receipt availability and real output dimensions are required for accepting results.

All size presets use the installed ResolutionSelector formula (1024² pixels/MP, Python ties-to-even). FLUX keeps its 16px grid. Krea/Qwen non-square presets use a 32px grid to avoid patch/latent alignment failures from the imports’ 8px selector; square defaults are unchanged. Edit source sizing follows the installed TextEncodeQwenImage21 source, including `resolution=0` rounding and optional per-reference pixel-budget resize. Predicted and actual output sizes are retained.

## Shared execution and safeguards

`canvas_recipe_jobs.py` shares immutable API preflight/transaction/queue behavior between the new image recipes and the H3 recipes. Uses existing board/document revisions, internal workflow registry, idempotency keys, uint64-safe seed storage, worker and the same global GPU lease. No new scheduler, database table or migration. Execution revalidates pinned project assets, graph/contract digests and cheap labeled model-identity hints. Late completion cannot replace a newer board draft or a deliberately selected historical result. Existing Canvas/image/video history and cloud provider settings are retained.

Profile switching preserves drafts and inputs. Image/edit inputs cannot silently become T2I conditioning; unsupported input fields are rejected before queueing. Deleting/reordering references cannot silently rebind prompt labels. Explicit Generate image/edit/board chat commands target the selected saved recipe; normal chat receives its current prompt/profile context. No hidden conversational model rewrite or workflow synthesis is added.

## Verification

Seven actual local GPU jobs passed through an isolated API, worker and asset ingestion (no user-project edits or cloud credits). Exact effective prompt receipts and output dimensions were verified:

| Case | Actual output |
| --- | --- |
| flux3-klein-t2i-v1 | 832 × 1248 |
| krea2-turbo-t2i-v1 | 1024 × 1024 |
| qwen21-t2i-v1 | 1024 × 1024 |
| qwen21-edit-v1 | 1344 × 768 |
| krea-style-portrait | 896 × 1184 |
| qwen-wide | 1376 × 768 |
| qwen-native-2k | 2048 × 2048 |

The FLUX/Krea/Qwen images retained the requested blue ceramic owl subject. The two-image Qwen edit changed the blue bowl to red while preserving the surrounding plant/table/daylight in the inspected result. These are sample checks, not a guarantee of perfect semantic editing across prompts.

Evidence: `data/image-boards/render-report.json`, `options-report.json`, `ui-report.json` and desktop/phone/light/dark screenshots. UI tests cover all four drafts, uploads, immediate input preview, source/custom sizing, full uint64 seeds, reload and real history; the actual Add Image board menu was exercised on desktop and phone with no render submissions. Backend regression suite: 123 tests. Frontend suite plus the new captured-profile/seed regression, TypeScript, changed-file lint and production build passed. Test projects/databases are isolated under `data/image-boards/`.

The incomplete `.crdownload` video file is not an image recipe and was not imported. No workflow originals, model files or external Block Party development files were modified. ComfyUI’s old process was holding its database without serving HTTP; after confirming no active Darius jobs, it was restarted using the installed launcher’s runtime. No nodes/models were installed.
