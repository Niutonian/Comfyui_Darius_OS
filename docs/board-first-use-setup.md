# First-use board preparation

Canvas boards carry a separate, portable Block Party dependency manifest under
`workflows/board-setup`. These manifests are bound to the existing versioned API
graph digest. They do not change rendering graphs, prompts, seeds, references,
dimensions or the adapters that submit and ingest the render.

When Generate finds missing models or nodes, it opens **Prepare board**. You can
also select a board in the Canvas overview and choose **Prepare board** directly.
The background check lists missing files, known download sizes, required node
packs and blockers. Preparation requires a confirmation of that particular plan.
Progress remains available after closing the window or reloading the browser;
repeat Generate or Prepare board to reopen it. Closing setup does not submit a
render. After a successful check/preparation, **Continue generation** retries the
exact saved request. Edits made while setup runs still trigger the normal server
revision check. Ready existing boards continue through the normal generation path.

Block Party downloads missing files into the configured ComfyUI model directories,
verifies SHA256, resumes supported partial downloads, and reuses matching models,
including supported shared `extra_model_paths` mappings. Files with the same name
but different contents are not replaced. Custom nodes are pinned to their author
revisions. Conflicting existing node revisions are reported rather than updated.
Node Python requirements are installed in ComfyUI's own Python environment.
Disk/network failures and missing credentials are reported in the setup panel.

The host must be on the Darius server. Set `COMFYUI_OUTPUT_DIR` or
`BLOCK_PARTY_COMFY_ROOT` correctly and use its loopback `COMFYUI_BASE_URL`.
On a new machine, Darius can detect the running ComfyUI from its verified local
listener. If detection is unavailable, expand **ComfyUI connection** in the setup
panel, enter its server address and folder, and choose **Save connection**. The
saved machine-local connection takes effect immediately and is loaded by future
workers. It does not overwrite provider keys or require editing environment names.
Portable parent folders are accepted; Darius locates their inner `ComfyUI` folder.
Process ownership uses native socket/PID information and the Python process's
actual working folder. Relative `main.py` launches work even when Python is
installed outside the ComfyUI folder. This adapter changes only inspection in
the private Block Party runtime; its queue, root-match and restart checks remain.
If Windows denies inspection, run ComfyUI and Darius under the same account and
elevation (normally both without Run as administrator), then Detect again.
Entering a folder does not authorize restarting an unrelated or unverified process.
An absolute custom output-directory launch flag is retained during detection;
the optional output-folder field can correct another nonstandard arrangement.
ComfyUI itself and its GPU drivers must already be installed. Missing built-in
nodes require a compatible ComfyUI update; Darius does not upgrade the host or
replace its PyTorch/CUDA installation automatically. Compiled optional kernels
still require compatible builds for that machine.

An idle restart can be allowed in the preparation panel. Block Party verifies
the listener belongs to the configured ComfyUI, checks its queue, and preserves
its launch arguments. A busy or unverifiable server is not restarted. While the
Block Party installation lock is held, Darius refuses new submissions to that
host. For H3 keyframe workflows, missing Block Party compatibility support is
prepared first; the next step reviews the model download plan after reloading
ComfyUI. Restart failures keep the saved board and setup report.

Gated downloads need the user's own `HF_TOKEN` or `CIVITAI_API_KEY` in the local
Darius `.env`, plus any model-provider license/access acceptance. Restart Darius
after editing those environment settings, then check again. Do not put tokens in
model URLs, manifests or shared ZIPs. Preparation does not accept publisher terms
on behalf of the user or change model licenses.
The current FLUX 3 download sources require Hugging Face access; these are marked
as authenticated downloads in its setup plan.

The first preparation downloads the tool from the author's public Block Party
repository at commit `dfabe49c77ae4dbffb65045c8ec61abe4453bb9c`. The private copy is
under ignored `data/tools/block-party`. Source changes in that tool are rejected.
The newer core `SaveImageAdvanced` sink is recognized through an in-memory adapter;
neither the Block Party development checkout nor the executable workflow changes.
Approval records live in Darius's private `data/board-setup/block-party-home`,
separate from standalone Block Party's machine configuration. Darius never calls
Block Party's render, watch or project execution engines.

FIBO can reuse a clean installed `comfyui-kjnodes` revision when its three
string-node implementations and input/output declarations match the reviewed
bundled implementation. Darius parses those classes without importing them,
checks the official Git origin and live node ownership, and pins the private
preparation contract to the actual installed commit. Its reuse receipt records
that commit and the source hash; changes invalidate readiness. The bundled
workflow and dependency package stay unchanged. Missing packs still use the
published pin. Other version conflicts, edited checkouts or different node
implementations remain blocked; clicking Check again cannot resolve them.
This compatibility rule applies only to bundled FIBO boards, never imported ZIPs.

Before rendering, Ollama's GPU handoff inspects `/api/ps` first. An empty resident
list needs no unload request, and a missing default model is never loaded just
to unload it. GPU-resident models are unloaded by their reported exact names,
then checked again. Confirmed CPU-only models are retained. An unavailable or
invalid residency report blocks rendering with an actionable error, except when
the local daemon explicitly refuses the connection because it is not running.

## Authoring another release

From a workstation with the intended models and node versions installed:

```powershell
.\.venv\Scripts\python.exe -B scripts/export-board-packages.py --block-party C:/path/to/BlockParty --sources C:/path/to/reviewed-model-sources.json
```

The optional sources file contains reviewed `folder`, `filename`, `url` records.
The script reads existing Block Party jobs and workflow UI model links, queries
publisher metadata, and pins compatible Hugging Face URLs to repository revisions.
Exported filenames can retain local aliases only when the source SHA256 matches.
It reads the author's ComfyUI and Block Party folders without modifying them.
All published packages must pass source/privacy review; do not distribute runtime
preparation state, download credentials or model weights inside the Darius ZIP.

Current coverage: all 11 bundled profiles have dependency contracts. Ten have
complete download sources. The reference-video recipe's locally installed
`minimax_h3_video_vae_int8_convrot.safetensors` (3,171,670,912 bytes,
SHA256 `9bb2d96f218c76babd85e0611b85ca8fb330a90546c01a0005e8a58a59593410`)
has no verified public download source. The similarly named official file has
different contents and is not silently substituted. Existing installations with
the matching file can use it; a fresh installation reports this specific missing
source until its author provides the correct URL or publishes a separate recipe.


## Readiness at a glance

Preparation now summarizes Darius/API/database, ComfyUI, the selected board,
optional chat and optional voice. Missing model access, missing dependencies,
node revision conflicts and a stopped/unconfigured ComfyUI have distinct remedies.
Use **Check connection** to open detection/manual connection controls, **Review
dependencies** for download sizes/blockers, and the chat/voice links for their
existing settings. Settings > Services also exposes the summary. Ollama is never
presented as required for board rendering. Configuration readiness is not a live
chat-quality or microphone test; use the existing Voice diagnostics.
