# Third-party components

Darius's original application code is licensed under [0BSD](LICENSE). Third-party
material retains its own terms. See [the attribution register](ATTRIBUTIONS.md)
for upstream projects, workflow/model credits and license boundaries, and the
[dependency inventory](docs/third-party/dependencies.json) for locked packages.
Attribution does not by itself grant permission to redistribute a workflow or model.

## Application dependencies

Dependency versions are pinned in `uv.lock` and `apps/web/package-lock.json`. Source releases contain dependency declarations; installed packages and compiled builds are excluded. Package metadata reviewed during preparation identifies these direct components:

| Component | Upstream license identifier |
| --- | --- |
| FastAPI, Pydantic, SQLAlchemy, JSON Schema, LangGraph | MIT |
| Requests, Hassil | Apache-2.0 |
| Next.js, React, React DOM | MIT |
| React Flow, Konva, React Konva, Zustand, Motion, TanStack Query | MIT |
| Lucide React | ISC |

Retain upstream copyright/license notices when distributing bundled dependencies. Transitive packages and optional runtimes have their own license metadata; the table is not an exhaustive legal compatibility assessment.

## Optional runtimes and services

The R2T2 Git submodule points at a pinned upstream commit. Its `LICENSE` identifies Apache-2.0 for the source; `MODEL_LICENSE` is a separate NetEase Youdao model use agreement. The source preview transfers the gitlink and `.gitmodules`, not the developer's installed checkout, checkpoints, logs or recordings.

ComfyUI, its custom nodes, Comfy MCP, llama.cpp, Ollama, Whisper, Pipecat, speech runtimes, FFmpeg and Caddy are separately installed components. Model weights, executables, installed environments and generated media are not included. Cloud API accounts and provider terms are separate from the Darius source license.

## Workflow provenance

Workflow templates retain their versioned provenance and graph checksums. The source snapshot's `release-provenance.json` documents removal of workstation paths/cached previews from authoring metadata, while executable API graphs and template digests remain unchanged. Original authoring artifacts are not part of the public development history.

Workflow/model names and authoring provenance do not themselves establish redistribution permission. Retain upstream licenses and notices for third-party workflow material; Darius's 0BSD grant covers its original contributions and does not replace those terms.
