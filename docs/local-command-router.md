# HassIL local command router

Darius uses **HassIL 3.12.1** for its existing media-control command path. It runs
in the Python API process on CPU: no separate service, model download, GPU memory,
API key or Home Assistant installation. Pipecat/Classic/cloud transcription and
the selected conversational/generation provider are unchanged.

## Request path

Transcription or typed message → HassIL intent/slots → existing project-scoped
presentation handler → validated client receipt → gallery/original-media viewer.

The initial catalogue covers gallery opening/filtering, full-size saved assets,
numbered/named gallery selection, next/previous/back/close, play/pause/stop/restart,
mute/unmute and bounded relative seeks. It does **not** invent workflows, render
media, change approvals, switch projects or delete files.

Examples now include “bring up my photo gallery”, “choose the 21st picture”,
“continue playing the video”, “stop playing it”, “jump ahead by fifteen seconds”
and “go back thirty seconds”. Existing documented commands remain supported.
Card numbers and asset ownership are still resolved against the originating
device's visible project gallery, not a model's recollection or another device.

## Catalogue and extension

`apps/api/darius_api/command_intents/en.yaml` holds the trusted English templates,
alternatives, expansion rules and typed lists. It ships as Python package data.
`command_router.py` compiles it once at API startup, supplies literal ordinal
aliases, normalizes politeness and maps recognized intents to allowlisted actions.
`media_controls.py` and `asset_presentation.py` remain responsible for execution,
managed-file checks and project/selection validation.

Edit the bundled catalogue as code, add positive/negative tests, and restart the
API to load changes. Adding a new intent does not by itself grant execution:
the adapter and existing receipt validator must explicitly support its action.
Do not add transcript/asset text as grammar templates or use global skip words
that could erase negation. Home Assistant's household command set is not loaded.

## Rejection and fallback

- Matches must cover the whole normalized sentence. Wildcard names cannot swallow
  generation/deletion instructions, negation, questions, or mixed-command tails.
- Finite/numbered intents outrank broad target wildcards. HassIL's literal-match
  specificity resolves optional article words and compound numbers (21 must not
  become 20 plus an optional “one”). Conflicting equally specific matches and
  excessive match counts ask for clarification; they execute nothing.
- No fuzzy matching or semantic nearest-route guess is enabled. Unsupported
  wording, genuine conversation and creative requests follow the existing
  selected-provider path. This includes negated requests: HassIL executes nothing;
  their conversational handling still depends on the chosen provider.
- Bare playback remains dependent on an actual selected media viewer; the voice
  transport's existing bare “stop” speech-interruption behavior is unchanged.
- Inputs, match count, seeks and gallery size are bounded. A 512-entry process-local
  decision cache avoids repeated grammar work; cached objects cannot be modified
  by callers. No match text or media content is sent anywhere by HassIL.

## Audit and installation

Local replies include `metadata.command_router` with engine, version, intent and
action. The existing Backend console logs a `local_command` event with those
fields and project ID, not the raw transcript or asset names. Conversation/task
IDs and original presentation receipts retain their previous behavior and retries
remain idempotent.

The dependency is pinned in `pyproject.toml`/`uv.lock`. For an existing setup:

```powershell
uv pip install --python .venv/Scripts/python.exe 'hassil==3.12.1'
```

Normal editable/wheel installation installs it automatically. No runtime network
download is required. Tests cover grammar variations, negatives, ambiguity,
ordinals, packaging, unchanged provider fallback, streamed receipts, gallery
ownership, unavailable models and idempotent retries.

Verified 2026-10-19: 192 backend tests passed; 18 fixture browser viewport/theme
cases passed (spoken gallery/video, continuous fullscreen voice and chat recovery).
The built wheel contains the YAML catalogue and pinned dependency; `uv pip check`
passed. API/web/proxy/LAN HTTPS returned HTTP 200 after restarting only the API.
No real model request, generation, microphone capture or user-project test messages
were used. Existing pinned dependency versions were preserved; the lock also now
records the previously declared jsonschema dependency.
