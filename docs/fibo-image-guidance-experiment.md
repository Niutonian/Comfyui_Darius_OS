# FIBO image-conditioned layout experiment

Status: **promising prototype; not integrated into production Canvas**. Tested ten real local renders on 23 October 2026. No saved user board, production workflow/profile, model weights, project asset selection or server process was changed. No cloud model was called.

## Source and experiment

The source is the immutable falcon composition at document revision 22, generation `9bfce88f-161b-47b3-a0e9-01f4bc0d960d`: clouds in the upper band, cave lower-left, pine tree lower-right and falcon upper-right. The original Dev seed is 4076737495. A second original/mirrored pair uses seed 888; the user's earlier text-only Turbo generation at that same seed/revision supplies a matched existing baseline.

Two references were tried:

1. A CPU-rendered labelled colour-block diagram made directly from the region rectangles. It contains no other project's assets and costs no image-model generation.
2. A MOSS render generated from the same saved composition/seed, then supplied as a semantic layout reference to FIBO.

The experimental API graphs connect `LoadImage` to `TextEncodeFibo2.images.image_1` and the existing VAE to `TextEncodeFibo2.vae`. This activates both visual reference encoding and reference latents in the installed FIBO node. Its latent output still drives KSampler; this does not treat its image as an ordinary empty text-only prompt. Both Turbo and Dev retain their actual checkpoints and baseline 4/30 steps, CFG 1/5, euler/simple, denoise 1, 1024 square and batch one.

The edit prompt is a real JSON object with `structured_caption` and `edit_instruction`. Its exact bytes are exposed by the PreviewAny receipt and checked against the submitted prompt. The photographic variants explicitly request a continuous photographic landscape and removal of diagram/painting/frame artifacts. This is an intentional experimental style instruction, not an unrecorded change to the user's saved prompt.

## Observed results

| Candidate | Observation | Local run time |
| --- | --- | --- |
| Text-only Turbo | Falcon lower-left and cave to the right; poor layout adherence | 8.91 s |
| Diagram → Turbo | Correct general positions; illustration/collage rather than one realistic scene | 16.45 s |
| MOSS layout image | Correct composition; chosen result has a painting/frame aesthetic | 19.41 s |
| MOSS → Turbo refinement | Holds positions but retains painting/frame style | 17.02 s after MOSS |
| MOSS → Dev refinement | Holds positions; still close to source appearance | 48.31 s after MOSS |
| Diagram → photographic Turbo | Correct main positions in a continuous landscape; bird pose can look pasted in | 21.84 s |
| Illustrated sketch → photographic Turbo | Mixed photographic background and outlined subjects; not preferred | 16.72 s after sketch |
| MOSS → photographic Turbo | Preserves composition and removes frame/painting appearance | 20.30 s after MOSS |
| Diagram → photographic Turbo, seed 888 | Falcon upper-right, cave lower-left, pine lower-right | 25.75 s |
| Mirrored diagram → photographic Turbo, seed 888 | Falcon upper-left, cave lower-right, pine lower-left | 15.45 s |

Times include local validation and collection, depend on cache/memory state and are not guarantees. The full MOSS + photographic Turbo route took about 40 seconds across its two renders in this batch. The direct diagram route avoids loading a second diffusion model.

All eight image-conditioned cases collected exactly one declared final SaveImage output, had the image and VAE connected in the actual submitted graph, and matched the exact recorded prompt receipt. These are qualitative visual assessments of a single composition family, not automatic segmentation/IoU scores. The reference and edit caption change together, so this is a workflow comparison, not proof that the image alone causes every improvement. The mirrored case follows the changed references and positional captions, rather than merely repeating the original composition.

## Limits and possible integration

The direct diagram route gives substantially better spatial guidance for this falcon case, but still does not impose hard pixel boundaries. It can produce an unnatural folded-wing bird floating in the sky, overly literal diagram style, extra objects or imperfect sizes. The MOSS route inherits the initial render's appearance and adds latency. These tradeoffs must remain visible; neither candidate is a proven universal replacement for the current workflows.

A future production integration should register an explicit image-conditioned profile and capability, generate its guide on CPU from the immutable snapshot, retain/upload that exact guide with project ownership and content hash, and preserve guide identity across retries/promotions. It should keep the existing shared worker/GPU lease and final-output sink filtering. Photographic style must be a visible choice, and further scenes, nesting, text, visibility, seed variation and interrupted retries should be tested before changing defaults. This experiment's helper uses a landscape-specific instruction and simple label rendering; it is not a generic production guide renderer.

## Artifacts

- `data/fibo-image-guidance/comparison.png` / `comparison.html`: actual outputs, source diagrams, and report-only dashed region overlays.
- `data/fibo-image-guidance/report.json`: source snapshot, seeds, prompt IDs, exact edit captions, reference hashes, submitted-graph digests, timing and visual review.
- `data/fibo-image-guidance/*.api.json`: the submitted experimental graph preparations.
- `scripts/render-fibo-layout-guide.cjs [--mirror]`: generate the diagram from the saved region geometry, without a model call.
- `scripts/check-fibo-image-guidance.py --run [--mirror-check]`: opt-in experiments. Completed cases are reused; an uncertain pending submission is never silently resubmitted.
- `scripts/report-fibo-image-guidance.cjs`: render the comparison without generating images.

The probe uses the real shared GPU lease and checks external ComfyUI occupancy before each run. Later probe diagnostics/job copies use an isolated runtime directory because the existing API/worker share a Windows rotating log that cannot be renamed while another process has it open. That unrelated logging issue did not invalidate the successful ComfyUI render/receipt checks; no production logging change was made here.
