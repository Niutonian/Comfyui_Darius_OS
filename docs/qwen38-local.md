# Qwen 3.8 ASCII local profile

This is an optional llama.cpp profile. It does not change Ollama, cloud credentials,
or the selected Darius conversational provider. Select **llama.cpp (local)** in
Darius Settings after starting its server.

## Download and start

From the project root in PowerShell:

```powershell
.venv\Scripts\python.exe scripts\download-qwen38.py
.\scripts\start-qwen38.ps1
```

The public GGUF download is resumable and requires approximately 12.25 GB of disk
space. The downloader verifies the published SHA-256 before activating the file.
The downloader writes to the ignored `data/models/llamacpp` directory. The launcher
also recognizes `%LOCALAPPDATA%\Darius\models\llamacpp` and prefers that cache when
the verified file is present there. On this PC, `E:` is an HDD and `C:` is an NVMe
SSD, so the installed weights use the latter cache to improve cold wakes. No model
repository code is executed. Existing downloaded models are not removed.

The default profile uses 16,384 tokens, Q8 K/V cache, 256-token micro-batches,
one parallel slot, Flash Attention and full GPU layer offload. It disables thinking
and has no vision projector. MTP plus ngram-cache are enabled with a two-token draft
limit after passing the local smoke test on this RTX 5080. Idle sleep after one second releases model GPU memory
so Darius can hand the GPU to ComfyUI; waking may add latency.

The server is loopback-only at `http://127.0.0.1:8080` and advertises:

```text
islamsidratul/Qwen3.8-27B-ByteShape-IQ4_XS-ASCII-GGUF:IQ4_XS
```

Set `LLAMACPP_MODEL` in `.env` to that alias and restart the API/worker when changing
profiles. Keep `LLAMACPP_BASE_URL=http://127.0.0.1:8080`. Do not change cloud keys or
`DARIUS_LLM_PROVIDER` just to install this profile; Darius' saved provider selection
remains separate. The generic `scripts/start-llamacpp.ps1` retains the previous
Qwen 3.5 9B default for switching back (also restore its `.env` model name).

For this large profile, set `LLAMACPP_UNLOAD_IDLE_COMFY=true`. Only llama.cpp uses
this opt-in: inside Darius' GPU lease, it checks the local ComfyUI queue and releases
idle model caches before waking. A busy or unrecognizable queue blocks the wake;
no queue is cleared and no job is cancelled. ComfyUI being stopped does not block
chat. Cloud providers and Ollama do not use this cache-release step.

## Checks and optional tuning

```powershell
.venv\Scripts\python.exe scripts\check-qwen38.py
# Optional experiments, stop the previous server first:
.\scripts\start-qwen38.ps1 -ContextSize 32768
.\scripts\start-qwen38.ps1 -SpecType none # Baseline without speculation
```

The smoke test uses only synthetic local prompts. It checks chat, native nested
tool arguments, image-subject retention and tool-result continuation; it neither
executes a tool nor renders media. Passing it is not a guarantee of perfect
workflow generation. Darius' validation and render-input review still apply.

Larger context is opt-in: measure VRAM, speed and tool correctness before using it.
A 16 GB GPU is also used by Windows and other apps.
Do not assume the Reddit user's AMD/Linux 45k-context or 40-token/s results apply
to this RTX/Windows installation. Leave enough free VRAM before waking the model;
avoid running ComfyUI and the model concurrently outside Darius' GPU handoff.

This installation uses the official portable llama.cpp b11015 CUDA 13.4 build
under `%LOCALAPPDATA%\Darius\bin\llama-b11015-cuda13.4`. Both release archives were
verified against GitHub's published SHA-256 digests. The profile prefers this
binary; the existing Winget/Vulkan installation and NVIDIA driver are untouched.
CUDA passed chat, native nested tool arguments and tool-result continuation.
The short continuation measured approximately 47 tokens/sec without speculation
and 70 tokens/sec with it; these are synthetic warm-test results, not promised
production throughput or end-to-end latency. Initial load was around six seconds.
A longer 384-token synthetic scene reached approximately 82 tokens/sec. Peak total
GPU use was 15,109 MiB, leaving around 870 MiB free after the driver reserve. Keep
the tested 16k context unless other GPU usage is reduced; 45k Q8 is not verified.

## Important limitations

This quant prunes non-ASCII/non-English vocabulary. Accented names and multilingual
input/output can degrade. Do not use it as a multilingual replacement for the
other providers. The linked repository supplies no `mmproj`, so this profile is
text-only; Darius' other vision-capable models remain available.

Sources: [model card](https://huggingface.co/islamsidratul/Qwen3.8-27B-ByteShape-IQ4_XS-ASCII-GGUF)
and [llama.cpp server options](https://github.com/ggml-org/llama.cpp/tree/master/tools/server).
