# Attribution register

Darius's original code and original contributions by Niutonian and Darius
contributors are licensed under [0BSD](LICENSE). This does not relicense models,
third-party workflows, libraries, runtimes or provider services. Model files,
executables, installed dependencies and personal/generated assets are not bundled.
Review date: 2026-10-27.

## Application dependencies

Exact versions are pinned in `uv.lock` and `apps/web/package-lock.json`.
[The dependency inventory](docs/third-party/dependencies.json) includes direct and
transitive locked packages and available license metadata. It is an inventory,
not a claim that all packages are bundled or every license legally assessed.
Unknown metadata is explicitly marked. Retain upstream notices when distributing
installed dependencies or compiled applications.

| Project / credited maintainers | Role | Declared license |
| --- | --- | --- |
| [Alembic / SQLAlchemy contributors](https://github.com/sqlalchemy/alembic) | Migrations | MIT |
| [FastAPI / Sebastián Ramírez and contributors](https://github.com/fastapi/fastapi) | HTTP API | MIT |
| [Hassil / Home Assistant contributors](https://github.com/home-assistant/hassil) | Local command matching | Apache-2.0 |
| [python-jsonschema contributors](https://github.com/python-jsonschema/jsonschema) | Contract validation | MIT |
| [LangGraph / LangChain contributors](https://github.com/langchain-ai/langgraph) | Retained orchestration/checkpoints | MIT |
| [Pydantic contributors](https://github.com/pydantic/pydantic) | Data models | MIT |
| [psutil / Giampaolo Rodola and contributors](https://github.com/giampaolo/psutil) | Process/socket inspection | BSD-3-Clause |
| [python-multipart contributors](https://github.com/Kludex/python-multipart) | Uploads | Apache-2.0 |
| [Requests / PSF and contributors](https://github.com/psf/requests) | HTTP client | Apache-2.0 |
| [SQLAlchemy / Michael Bayer and contributors](https://github.com/sqlalchemy/sqlalchemy) | Persistence | MIT |
| [Uvicorn / Encode and contributors](https://github.com/encode/uvicorn) | ASGI server | BSD-3-Clause |
| [Next.js / Vercel and contributors](https://github.com/vercel/next.js) | Web framework | MIT |
| [React / Meta and contributors](https://github.com/facebook/react) | UI | MIT |
| [TanStack Query contributors](https://github.com/TanStack/query) | Client synchronization | MIT |
| [React Flow / xyflow contributors](https://github.com/xyflow/xyflow) | Graph UI | MIT |
| [Konva / React Konva / Anton Lavrenov and contributors](https://github.com/konvajs/konva) | Canvas | MIT |
| [Zustand / pmndrs contributors](https://github.com/pmndrs/zustand) | UI state | MIT |
| [Motion contributors](https://github.com/motiondivision/motion) | Animation | MIT |
| [Lucide contributors](https://github.com/lucide-icons/lucide) | Icons | ISC |
| [TypeScript / Microsoft](https://github.com/microsoft/TypeScript) | Development tools | Apache-2.0 |
| ESLint, Vitest, Testing Library, jsdom, DefinitelyTyped contributors | Development/tests | MIT; individual packages in inventory |

## Separately installed ComfyUI components

These are integrations, not vendored node implementations. Their own terms apply
when installing or distributing them. The source preview does not include their
Python packages, environments, model files or rendered examples.

| Project / credited creator | Source / terms |
| --- | --- |
| Comfy Org, comfyanonymous and contributors | [ComfyUI](https://github.com/Comfy-Org/ComfyUI), GPL-3.0 license text |
| Comfy Org workflow contributors | [workflow_templates](https://github.com/Comfy-Org/workflow_templates), MIT; [retained copyright/license](docs/third-party/licenses/comfy-workflow-templates-MIT.txt) |
| Niutonian / Block Party contributors | [Comfyui_BlockParty](https://github.com/Niutonian/Comfyui_BlockParty), separately downloaded pinned preparation tool; not relicensed by Darius |
| Comfy Org / comfy-cli contributors | [comfy-cli](https://github.com/Comfy-Org/comfy-cli), separate CLI bridge |
| kijai and contributors | [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes), GPL-3.0 license text; FIBO string helpers and other utilities |
| yolain and contributors | [ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use), GPL-3.0 license text |
| Kosinkadink and contributors | [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite), GPL-3.0 license text |
| rgthree and contributors | [rgthree-comfy](https://github.com/rgthree/rgthree-comfy), MIT |
| xmarre; original LBH-123-AI contributors | [MiniMax H3 Latent Upscaler-Plus](https://github.com/xmarre/Comfyui_Minimax_h3_latent_Upscaler-Plus), [upstream](https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler); consult upstream terms |
| jlucasmcrell; joeygambino | [H3-Multishot](https://github.com/jlucasmcrell/ComfyUI-H3-Multishot), [Seamless Chain workflow](https://huggingface.co/joeygambino/MiniMax-H3-Multishot-Workflow); workflow card declares Apache-2.0 |

## Workflow and model provenance

A model card's license does not automatically license an independently authored
workflow. Original workflow creators retain their rights. Darius adaptations do
not grant rights to redistribute weights. Board setup manifests record exact
model files, hashes, sources and node revisions; Canvas manifests retain source
checksums. Credits embedded in source notes remain with those source files.

| Board / material | Credited upstream sources |
| --- | --- |
| MOSS layout board | [OpenMOSS / OpenMOSS-Team](https://github.com/OpenMOSS/MOSS-Image), [Comfy Org repackaging](https://huggingface.co/Comfy-Org/MOSS-Image); model card declares Apache-2.0 |
| FIBO Dev and Turbo | [BRIA AI / FIBO 2.0 Dev](https://huggingface.co/briaai/Fibo-2.0-dev), [Edit Turbo](https://huggingface.co/briaai/Fibo-2.0-edit-turbo), and [Comfy Org repackaging](https://huggingface.co/Comfy-Org/Fibo-2.0); weights are copyright BRIA AI under **CC-BY-NC-4.0**, not 0BSD. KJNodes string-chain semantics are acknowledged; only compatibility fingerprints, not KJNodes implementations, are stored in Darius |
| FLUX 3 Klein and prompt upsampler | [Black Forest Labs](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy); [FLUX Kommunity License](https://huggingface.co/black-forest-labs/flux-3-image-klein/blob/main/LICENSE.md) has separate model-use conditions |
| Krea 2 Turbo | Krea, [Comfy Org repackaging](https://huggingface.co/Comfy-Org/Krea-2) and official workflow contributors; model-specific terms apply |
| Qwen Image 2.1 T2I/edit and Qwen encoders | Qwen team / Alibaba, [Comfy Org repackaging](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) and workflow contributors; exact model licenses apply |
| MiniMax H3 animation/camera | MiniMax, [Comfy Org repackaging](https://huggingface.co/Comfy-Org/MiniMax-H3) and associated workflow creators |
| H3 Body swap | Niutonian's supplied Darius BodySwap workflow; MiniMax / Comfy Org base models; [Alissonerdx Character Swap](https://huggingface.co/Alissonerdx/Minimax-H3-ComfyUI), [drbaph Turbo LoRA](https://huggingface.co/drbaph/MiniMax-H3-Turbo-Lora-ComfyUI), and [1038lab RMBG](https://github.com/1038lab/ComfyUI-RMBG). Model and node terms remain separate; author-supplied Recast/Ollama node implementations are not bundled |
| Reference-video / Singularity | [WarmBloodAban](https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity); model card declares Apache-2.0; workflow rights assessed separately |
| H3 camera-motion LoRA | [Jojocodex](https://huggingface.co/Jojocodex/minimax-h3-Camera-Motion-lora) |
| H3 Turbo LoRA / approximate VAE | [Kijai](https://huggingface.co/Kijai/MiniMax-H3_comfy), [MiniMax-H3-TAE](https://huggingface.co/Kijai/MiniMax-H3-TAE), original LightX2V acceleration contributors |
| H3 latent upscaler weights | [LBH-123-AI](https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler) |
| Optional Ornith 1.5 9B chat | [Ornith team](https://huggingface.co/ornith-ai/Ornith-1.5-9B), [Ollama distribution](https://ollama.com/library/ornith-1.5:9b) |

Examples in source authoring files can reference optional models/helpers that
are not used by the compiled board. They are not instructions to install them.
Apache-2.0 license text is retained in [the license directory](docs/third-party/licenses/Apache-2.0.txt)
for material distributed under that license. Copyright remains with its authors.

## Other optional runtimes and services

- [Ollama contributors](https://github.com/ollama/ollama) and
  [llama.cpp / ggml contributors](https://github.com/ggml-org/llama.cpp): local LLM servers.
- [OpenAI Whisper](https://github.com/openai/whisper),
  [SYSTRAN faster-whisper](https://github.com/SYSTRAN/faster-whisper),
  [Pipecat contributors](https://github.com/pipecat-ai/pipecat) and speech model
  publishers named in the voice guides: separately installed speech stack.
- OmniVoice, PyTorch/TorchAudio, Hugging Face Transformers, Alpha Cephei Vosk,
  websockets and HTTPX contributors: additional separately installed voice
  dependencies pinned in `apps/voice/requirements.txt`. Their upstream license
  notices remain with the installed packages; speech checkpoints retain their
  own model licenses.
- NetEase Youdao / Confucius4-R2T2 contributors: optional pinned submodule;
  Apache-2.0 source and a separate `MODEL_LICENSE` agreement for weights. The
  release transfers the gitlink/URL, not the installed checkout or checkpoints.
- [FFmpeg contributors](https://ffmpeg.org/legal.html): terms depend on the exact
  separately installed build and enabled components.
- [Caddy contributors](https://github.com/caddyserver/caddy): optional LAN HTTPS.
- Astral / uv, Python, Node.js, Git and Microsoft WinGet contributors:
  development and installation tools, not bundled executables.
- OpenAI, DeepSeek, OpenCode and Black Forest Labs: optional service providers;
  their accounts, API terms and trademarks remain separate from Darius.

Use the license attached to the exact upstream file/revision. Do not assume that
every component of a Darius installation is licensed under 0BSD.
