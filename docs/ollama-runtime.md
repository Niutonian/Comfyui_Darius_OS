# Ollama runtime profiles

Darius uses Ollama's native `/api/chat` endpoint for Ollama only. This makes
`options.num_ctx` effective; the OpenAI-compatible endpoint cannot configure
that setting. No cloud transport or llama.cpp transport is changed.

## This installation

`ornith-1.5:9b` is configured for **131,072 tokens** and `ornith-1.5:35b` for
**32,768 tokens**, with up to **8,192 output tokens** reserved for structured
planning (including thinking). These are exact model-name overrides: a 9B
setting does not apply to the 35B tag. B describes model parameters, while K
describes context tokens; the configured window is not the model's theoretical
maximum. Ordinary
streamed conversation uses a 2,048-token reply cap and disables thinking for
responsive voice/chat. The model is unloaded before releasing the GPU lease.

Ornith's published precise-task sampling is used for structured/tool turns:
temperature 0.6, top-p 0.95, top-k 20, min-p 0, presence penalty 0, repeat
penalty 1. General conversational turns use temperature 1 and presence penalty
1.5. No private thinking text is published to chat or voice.

The RTX 5080 16 GB smoke checks on 2026-10-22 covered:

| Allocated context | Check | Actual prompt tokens | Result |
| --- | --- | --- | --- |
| 32,768 | Structured subject/action JSON | 1,821 | Correct |
| 65,536 | Structured subject/action JSON | 5,341 | Correct |
| 131,072 | Native fixture tool call | 5,598 | Correct function and object arguments |
| 131,072 | Structured subject/action JSON, truncation disabled | 5,341 | Correct |
| 131,072 | Vision: synthetic red square | 36 reported by Ollama | Correct color |
| 131,072 | Streaming plain conversation | 27 | Completed correctly |

At 128K Ollama reported 9,897,110,404 resident bytes, all on GPU. Total GPU use
was approximately 12.5 GB (MiB-reported values 12,527–12,539), leaving about
3.4 GB. These are short smoke tests at the allocated limit, **not full-128K
input stress tests or a guarantee of worst-case vision/long-context memory**.
The original failure was a 5,123-token input rejected by a 4,096-token runtime.
No real workflow was submitted during these tests.

The 35B Q4_K_M model also passed a native fixture tool call at 65,536 context
tokens (5,598 actual prompt tokens). However, total GPU use reached 15,560 MiB,
leaving only 418 MiB free. This installation therefore keeps 35B at 32K rather
than deploying the tested 64K profile with inadequate memory headroom. The
larger weights also require CPU offload on this 16 GB card.

## Configuration

```dotenv
OLLAMA_CONTEXT_TOKENS=16384
OLLAMA_MODEL_CONTEXTS={"ornith-1.5:9b":131072,"ornith-1.5:35b":32768}
OLLAMA_UNLOAD_IDLE_COMFY=true
```

Restart the Darius API after changing these settings. Values are per-request:
no Ollama-wide environment settings, model files, templates, or quantizations
are overwritten, and no duplicate model aliases or weight downloads are made.
Other Ollama models use the 16K default unless overridden; Ornith's portable
code default is 32K. Metadata caps requests at the model's advertised maximum.
If memory becomes tight, lower the Ornith override to 65536 or 32768.

Under the exclusive GPU lease, Darius releases only **idle** local ComfyUI
model caches before waking Ollama. Busy or unknown queues are not modified;
no render is interrupted. Ollama is unloaded and verified absent on exit so
ComfyUI can reclaim VRAM. The handoff switch is independent of llama.cpp's.

The handoff uses Ollama's running-model list rather than the configured default
model name. No GPU-resident models means no unload request. Reported GPU models
are unloaded by exact name, with release verified before ComfyUI can proceed.
Confirmed CPU-only models are kept. Missing defaults on fresh installations
therefore do not block Canvas. HTTP failures report their status and stage;
invalid or timed-out residency checks are never treated as successful release.
See [running models](https://docs.ollama.com/api/ps) and
[unload with keep_alive](https://docs.ollama.com/api/generate).

## Prompt budgeting and errors

The budget reserves output space and template headroom. Ollama does not expose
the public template/tokenization endpoints used by Darius' llama.cpp adapter,
so Ollama uses a conservative **UTF-8-byte-based textual bound**, not an exact
tokenizer count. Attached image base64 is excluded from text counts; each image
reserves 8,192 tokens. This image reserve is a heuristic, not an exact vision
token count. Actual prompt/output counts are logged after successful requests.
Text is counted as supplied to the template, without counting JSON transport
escaping a second time. If fitting fails with an 8K output allowance, Darius
tries 4K and then 2K allowances locally before rejecting the request. These are
CPU-only budget checks, not repeated model calls. Current instructions are
never shortened to make room for optional reasoning space.

Only copies of old background conversation/events and redundant tool evidence
are compacted. Native `truncate` and `shift` are disabled so the server cannot
silently remove history when its actual tokenizer disagrees with the estimate.
Current user instructions, production/asset IDs, recent context,
and tool-call/result pairing are retained. Saved chats/checkpoints are not
rewritten. If protected context cannot fit, the request stops with a helpful
budget error rather than silently truncating its subject.

Console records model, configured context, reserved output, estimated input
bound, actual usage, timings and failure details—not request bodies or private
thinking. HTTP errors retain bounded/redacted server explanations. Incomplete
streams, thinking-only replies and exhausted output limits are not recorded
as success. One bounded, tools-disabled final-format repair is permitted for
Ollama after a completed but malformed answer; this cannot replay a tool or
render. Transport failures, renders and cloud payments are not automatically
retried.

## Reusable workflow routing

Explicit, unambiguous selections such as "run it with Moss" can resolve an
imported multiword recipe name. The visual brief receives the selected
renderer's identity separately from scene subjects. Ambiguous aliases ask for
clarification instead of silently falling back to another workflow.

For server-routed text-only recipes, viewed/contextual images are not physical
workflow inputs. Explicit attachments and pinned references are still checked
and must be bound or rejected, never silently discarded. Simple workflow-list
questions can use a confirmed catalog tool receipt directly, avoiding an
unnecessary second model turn; informational replies cannot propose a render.

These changes apply to future Block Party imports too. Import registers the
declared API graph/contract and refreshes the UI list, without installing models
or nodes or executing a job. Check dependencies/input mappings, then save the
desired Use for / Default association. An identical re-import preserves the
existing package; changed content receives a new identity and should be
checked and associated as a new recipe. Existing jobs are not rerendered.

### Catalog and inspection corrections (2026-10-22)

Chat's `list_workflows` now queries the same Darius base-recipe catalog as
Create, including imported Block Party recipes and cloud operations, rather
than Comfy's separate CLI list when a defaults folder is configured. Trusted
policies still restrict that catalog. Local prompts retain up to 64 lightweight
workflow identities and the selected renderer, not full contracts. Omission
from a bounded prompt is explicitly not evidence that a workflow is missing.

Registered tool inspections retain the authoritative manifest (roles, values,
digests, readiness and parameter bounds) once. Duplicate graph, slot and prompt
views and identical parameter defaults are omitted from transport copies;
saved checkpoints and graphs are untouched. Budget rejections log only sizes
and counts, never the user text, before any inference starts.

Spoken aspect ratios such as "16 by 9 image" no longer count as nine outputs.
Focused workflow-name answers can reconnect to an unfinished generation request,
but cannot cross a queued job, cancellation or new user topic. Known Block Party
settings such as aspect_ratio are not scene prompt fields. Existing unresolved
scene mappings still require a user decision; system/negative text stays protected.

Reusable local-only fixture checks (refuse a busy ComfyUI queue):

```powershell
.venv\Scripts\python.exe scripts/check-ollama-profile.py --model ornith-1.5:9b --context 131072 --probe tools
.venv\Scripts\python.exe scripts/check-ollama-profile.py --model ornith-1.5:9b --context 131072 --probe vision
```

Sources: [Ornith model card](https://huggingface.co/ornith-ai/Ornith-1.5-9B),
[Ollama context length](https://docs.ollama.com/context-length),
[native chat](https://docs.ollama.com/api/chat),
[OpenAI compatibility](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx).
