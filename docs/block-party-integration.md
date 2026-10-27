# Block Party integration assessment

Integration: 2026-10-18. Declarative job import and read-only dependency checks.
Importing a ZIP never executes Block Party or package code.

Update 2026-10-27: the import/readiness endpoints below remain read-only. Bundled
Canvas boards now have a separate, explicitly confirmed
[first-use preparation flow](board-first-use-setup.md) using a private pinned
Block Party runtime. That flow can install declared dependencies and request an
idle restart; it does not give imported ZIPs permission to install automatically.

Sources: [Block Party](https://github.com/Niutonian/Comfyui_BlockParty),
[job contract and preparation](https://github.com/Niutonian/Comfyui_BlockParty/blob/main/one_job/job.py),
[input slots](https://github.com/Niutonian/Comfyui_BlockParty/blob/main/one_job/slots.py),
[export readiness](https://github.com/Niutonian/Comfyui_BlockParty/blob/main/one_job/readiness.py).

Block Party is useful as a portable recipe contract, not as a replacement LLM.
Its job format declares workflow files, media slots, editable parameters, models
and node dependencies. Its checks bind local preparation to graph/manifest hashes,
model hashes and installed node versions/content. Shared preparation files do not
grant approval on the receiving machine. Declared slots are checked against the
graph; multi-reference assignments retain separate named roles.

Adapter responsibilities:

1. Import a job's graph and manifest into the base-recipe catalog, without
   executing package code. Translate declared prompt, reference, size and seed
   parameters into Darius's source-bound registration contract. Require explicit
   mapping of scene versus system/negative text; reject conflicting mappings.
2. Add a read-only readiness report before model planning: missing files,
   incompatible node versions, incomplete references and unsupported slots.
   Keep model hashing off the per-message hot path using bounded identity-aware
   caching. Reports must not imply that a workflow fits available VRAM.
3. Leave dependency preparation to Block Party. Darius does not download models,
   install nodes or restart ComfyUI when a recipe is imported or selected.

## Using the integration

1. Export **one job ZIP** from Block Party, with its `manifest.json` and one API
   workflow. Expose the positive scene prompt and only the dimensions/settings/
   seeds that Darius may change. Prefer no bundled examples; the upload limit is
   64 MiB. Project chains and multiple workflow variants need separate exports.
2. In Darius, open **Create → Trusted workflows → Import Block Party ZIP**.
   Import adds an immutable recipe under `workflows/defaults/block-party`.
   Importing the same graph/contract again reuses the existing recipe. A new
   export/version receives a new ID; current defaults are not silently replaced.
3. Click **Check dependencies** on the imported row. Missing models, changed
   hashes, missing/modified node packs and incompatible loaded classes are shown.
   Prepare/install the intended versions in Block Party, restart ComfyUI yourself
   when required, then check again. The check does not render or allocate model
   VRAM, but hashing large model files can take time. Hashes are cached only while
   file identity/size/timestamps remain unchanged in the current API process.
4. Choose **Register inputs**. Inspect the scene/preserve mapping, then select
   **Use for**, select **Default**, and save the global or project selection.
   Fields not exposed by the package author cannot be made editable from Darius.

For local dependency verification, Darius uses the parent of
`COMFYUI_OUTPUT_DIR`, or an explicit `BLOCK_PARTY_COMFY_ROOT` server setting.
The directory must contain ComfyUI's `main.py` and `folder_paths.py`.
Standard model folders and the unet/diffusion_models and clip/text_encoders
aliases are supported. External `extra_model_paths` locations are not inferred.
Node checks require the declared pack to be its own Git checkout at the pinned
commit without local changes. Installed node origins are checked against the
running ComfyUI instance; restart it after reinstalling/updating node packs.

## Enforcement and current limits

Only graph/contract JSON is published; ZIP paths/links, duplicate JSON keys,
embedded credentials, inconsistent media slots and invalid parameter bounds are
rejected. Scripts, model binaries, bundled inputs, outputs and preparation state
are never extracted. A changed graph or detached contract invalidates the recipe.
Only declared editable parameters may be overridden; defaults and bounds are
checked. Darius-generated output paths are still managed by Darius. Only exposed
seed inputs are randomized. Raw graph-copy preparation cannot replace the
declared-input path after a package is inspected.

Image and image-to-video jobs bind named image inputs to active-project assets;
bundled example images are never fallback references. Video/audio loader inputs
currently produce an explicit unsupported-binding blocker. Export a compatible
image-input recipe until those adapters exist. Additional runtime requirements
are reported, not imported/probed by executing arbitrary code. Readiness does
not grant render permission: unknown/custom/API nodes still follow Darius's
existing review policy. Live ComfyUI validation remains mandatory at preparation.

Endpoints:

- `POST /api/v1/workflow-recipes/block-party/import`: multipart `file` ZIP.
- `POST /api/v1/workflow-recipes/block-party/readiness`: `{workflow_id}`.

Import and readiness never select defaults, create jobs, invoke models or start
dependency installation. Prepared exports are still needed to validate real
user workflows; fixture checks do not certify an untested package.

Darius should retain project asset IDs, subject/count validation, review digests,
job idempotency and its single submission authority. Block Party would explain
what a recipe accepts and needs; Darius would decide which project assets and
brief fill it, and whether execution is authorized. Do not run both submission
engines for one request or treat a package's metadata as permission to execute
unknown Python nodes, paid services, bundled state or example project media.

This could reduce guessed input bindings and dependency surprises, but cannot
guarantee correct third-party code, model output or crash-free GPU execution.
