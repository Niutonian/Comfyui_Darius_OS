# FIBO region adherence: confirmed defect

Follow-up: [image-conditioned guidance was tested on the falcon composition](fibo-image-guidance-experiment.md). It substantially improves placement, including a mirrored layout, but remains a prototype with pose/style limitations. Production profiles are not changed by that experiment.

Status: **flat-shape adherence issue reproduced; exact saved ComfyUI example also reproduced through Darius with pixel-identical output**. Six real local GPU renders on 23 October 2026 reproduced the user's report. The production app, saved boards, historical workflows and MOSS adapter were not modified during these tests.

The initial FIBO integration checked exact delivery of its supplied instruction-string workflow. That proves payload integrity, not spatial adherence, and was insufficient as acceptance of Canvas region control.

## Controlled comparison

One solid red rectangle on white, 1024 square, seed 42. The left target is x=5–30%, y=25–75%; the right target is x=70–95%, y=25–75%. The global description and object description remain identical; only the region's X coordinate changes. FIBO uses Dev at 30 steps / CFG 5, MOSS its existing 25-step / CFG 2.5 preset. No cloud models, image editing, postprocessing or generated-image compositing were used to produce the results.

Overlap is intersection-over-union of the actual generated red-pixel mask and target rectangle. The mask requires R>130, R>1.5G and R>1.5B. These simple flat-colour tests make an objective check possible; this is not a general scene/object-detection benchmark.

| Workflow | Left overlap | Right overlap | Generated horizontal centers |
| --- | --- | --- | --- |
| Current FIBO Dev (`fibo-dev-v1`) | 15.99% | 12.66% | 49.95%, 49.95% |
| MOSS (`moss-bboxes-v1`) | 98.47% | 98.44% | 17.57%, 82.52% |
| FIBO native JSON candidate | 32.87% | 33.22% | 27.09%, 73.94% |

Requested centers are 17.5% and 82.5%. At a 90% overlap acceptance threshold, MOSS passes both; neither FIBO path passes. Native JSON improves direction but still oversizes/misplaces the object. It must not be deployed or described as accurate region support based on this result.

## Observed conditioning and limits

The supplied FIBO workflow sends an instruction plus comma-separated Python dictionaries containing `type`, `bbox` (TLBR 0–1000), and `desc` into TextEncodeFibo2. Those are CreateBoundingBoxes / Ideogram-style elements. Installed `comfy/text_encoders/fibo2.py::parse_prompt` only treats a JSON object as a structured caption; this supplied string remains freeform text. No spatial mask, regional attention or image/latent layout conditioning is connected. The numerical box arriving unchanged does not make it a model-native spatial control.

MOSS instead receives its adapter's own structured layout representation. Its output tracks both coordinates and size in this test.

The candidate uses real JSON with FIBO's documented `short_description`, `objects`, `location`, `relative_size`, `appearance_details`, `aesthetics` and `text_render` fields. No invented numeric bounding-box field or hidden LLM rewrite was added. Geometry becomes explicit positional/percentage strings in supported fields. The model reacts to left/right, but this remains semantic guidance rather than MOSS-equivalent box control.

Primary references: [official FIBO 2.0 pipeline documentation](https://huggingface.co/docs/diffusers/main/api/pipelines/bria_fibo2), [Bria VGL generation field guide](https://github.com/Bria-AI/vgl/blob/dev/src/bria_vgl/dialects/thales/input_schema/generate.txt), [Bria VGL output schema](https://github.com/Bria-AI/vgl/blob/dev/src/bria_vgl/dialects/thales/output_schema/generate.json). The exact downloaded schema/guide and installed runtime/compiler provenance are retained alongside the test artifacts.

## Artifacts and next acceptance gate

- `data/fibo-layout-debug/comparison.png` and `comparison.html`: actual images with requested boxes overlaid as dashed green guides. Original output PNGs remain separate.
- `data/fibo-layout-debug/spatial-report.json`: prompt IDs, actual measurements, seed, prepared graphs and provenance, plus an explicit rejected-candidate verdict.
- `scripts/check-fibo-layout.py --run`: opt-in real renders, shared local GPU lease and external-queue check. It reuses completed case artifacts on rerun; use a separate output location or archive the report for a deliberate fresh batch.
- `scripts/report-fibo-layout.cjs`: renders the comparison report without generating images.

For another failing composition, first replay its exact inputs and settings in ComfyUI before attributing the difference to the adapter or changing conditioning. Any future layout strategy must be separately versioned and tested for placement, scale, multiple regions and nested regions before promotion, while preserving historical replay. MOSS meets the flat-rectangle gate; the tested FIBO cases do not.

## Corrected conclusion after exact ComfyUI comparison

The user's working manual execution was found in ComfyUI history and reproduced through the actual Darius compiler/provider path with the same global scene, region descriptions, boxes, palettes, seed 64 and sampler/model settings. The original and Darius reproduction have identical decoded RGB SHA-256 `0a54c265db24bbb840f8525024d95943b740a0be5f9d18608e59f80ea2e289f7`. The active ComfyUI graph uses the same freeform conditioning chain, with no hidden layout processing. Therefore the earlier suggestion that this format mismatch itself explained the ComfyUI-versus-Darius discrepancy was premature. The flat-rectangle benchmark demonstrates a failure on those inputs, not a universal inability to reproduce a working FIBO scene.

The original scene is a rich interior still-life description with two described/paletted objects; recent Darius graphs include examples with an empty global scene. These are different prompts, not an apples-to-apples execution comparison. The correct comparison must hold every input and setting fixed before diagnosing an adapter defect.

A separate confirmed import defect dropped the optional supplied example's source box widgets during CLI UI-to-API conversion. This did not drop live board boxes, which the compiler replaces explicitly. Load supplied example now restores its hash-verified original UI widgets and palettes. The live FIBO conditioning chain remains the same; no unproven JSON replacement was deployed.
