# Voice gallery and original-media controls

These commands work in Talk and fullscreen voice (Pipecat, Classic, or cloud
transcription), through the shared chat submission path. They also work as text.
Common commands are resolved before the planner: no model tokens, rendering,
credits, workflow changes or automatic generation attachments.

Recognition now uses the CPU-only [HassIL command catalogue](local-command-router.md),
not the former hand-written command regex chain. Existing scoped execution and
viewer receipts remain authoritative; normal conversation keeps its selected model.

## Try it

- “Open the gallery” — numbered original images/videos, newest first.
- “Open the image gallery” or “show my video gallery” — filter by media type.
- “Open image three”, “choose the second picture”, “select Forest opening” —
  open a card by its displayed number or a unique saved name.
- “Play video three” — open that numbered card and request playback.
- “Open the latest video fullscreen and play it” — open a saved video directly.
- “Play the video”, “pause the video”, “stop video”, “restart the clip”.
- “Mute the video”, “unmute it”, “skip forward ten seconds”, “rewind 20 seconds”.
- “Next image”, “previous asset”, “back to gallery”, “close gallery”.

Card numbers refer to the **whole visible gallery**, not the third video among
images. Search preserves the original numbers. Spoken numbers/ordinals work
through 48. Ambiguous names or out-of-range numbers ask for a numbered selection.
The gallery is intentionally bounded to the latest 48 saved media records; older
assets can still be opened by saved name via existing project search. Missing
original files and derivative thumbnails are excluded. Nothing is regenerated.

“Open it full size” still uses the media discussed in this conversation, not an
arbitrary project asset. Explicit latest requests may use the latest matching
project asset. Unfinished renders do not open an older unrelated result.

## Playback and session behavior

Full size uses Darius's fitted original-media overlay, not OS/browser-exclusive
fullscreen; it keeps the continuous voice transport alive and supports `playsInline`
on mobile. Browsers can block unprompted playback or sound. A failed `play()` shows
an explicit tap-to-play hint, never a false claim that playback succeeded. The
viewer also has visible Play/Pause, Stop, Restart, Mute and Back to gallery controls.
Stop pauses and returns to time zero; closing/navigating away pauses the old media.
Seeks clamp to loaded media duration and allow at most 600 seconds per command.

Escape/Close dismisses only the gallery/media overlay, not fullscreen voice or its
microphone. “Stop video” controls media; bare “stop” retains the voice transport's
existing speech-interruption meaning. Headphones can reduce video sound leaking
back into a live microphone. No voice model or audio-service settings are changed.

## Scope and safety

Each outgoing turn includes a device-local snapshot of the open gallery's IDs,
index and mode. The server revalidates ownership, original kind, managed storage
and file existence. Numbered selections cannot use a gallery from another device
or merely the last gallery mentioned in saved history. The frontend validates
scope/identity again, rejects late selections after a gallery closes/changes, and
only applies playback to the currently selected original video/audio.

Presentation receipts contain no executable code, URLs or local paths. Only new
replies requested by the originating browser apply actions. History loads and
remote conversation sync do not replay them. Replies are deduplicated and leaving
the project/thread invalidates pending media fetches. `present_assets` provides
the same bounded validated actions for more conversational model-driven requests;
`view_assets` remains model vision, not a UI command.

## Verification

Backend: `tests/test_asset_presentation.py` plus harness, streaming, chat recovery
and media regressions. Frontend: `use-asset-presentation.test.ts`,
`voice-gallery.test.tsx`, `asset-preview.test.tsx` and workspace tests include
blocked autoplay, exact ownership, original source, selection order, stop/seek,
deduplication and late-response guards.

`scripts/check-voice-gallery.cjs` injects silent synthetic microphone audio and
Pipecat transcripts, intercepting **all** app/voice APIs. It checks real browser
video playback and continuous voice at mobile/desktop/landscape sizes in both
themes. Generate its tiny CPU-only video fixture first:

```powershell
New-Item -ItemType Directory -Path data/voice-gallery-audit -Force
ffmpeg -hide_banner -loglevel error -f lavfi -i 'color=c=0x526a57:s=640x360:r=10' -t 12 -c:v libvpx-vp9 -b:v 80k -y data/voice-gallery-audit/fixture.webm
$env:DARIUS_PLAYWRIGHT_MODULE = '<installed Playwright module path>'
node scripts/check-voice-gallery.cjs
```

Screenshots and the fixture stay in ignored `data/voice-gallery-audit/`. No real
microphone, model request, project data writes or ComfyUI execution are used.

Verified 2026-10-19: 207 frontend tests, 124 targeted backend regressions, targeted
ESLint, production build/type checking, and 26 browser viewport/theme cases
(6 spoken-gallery/playback, 8 fullscreen, 8 context/shot browsing, 4 chat recovery).
Local web, API proxy and LAN HTTPS returned HTTP 200 after restarting only API/web.
