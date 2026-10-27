# Fullscreen voice sessions

Open **Fullscreen voice** from the conversation controls. The live space uses
the current project, conversation, model selection, and saved messages. It is a
view of the existing conversation, not a separate memory or workflow engine.

- Saved turns and streamed replies appear in one continuous, scrollable flow.
- The presence orb contracts once a conversation starts so more space is left
  for captions, images, and video. Status reflects speech playback before a
  still-running backend request; it does not claim a render has completed.
- New text and loaded media stay at the live edge. Scrolling up by wheel, touch,
  scrollbar, or keyboard suspends following; **Back to live** restores it.
- Caption visibility does not hide media results or approval controls.
- Completed jobs and multi-shot results can be inspected within the session.
  Native full-size media previews own Escape until the preview closes.
- **Review generation here** opens the existing action-plan review inside
  fullscreen. Required validation and approval are unchanged; merely opening
  the review does not queue anything or select a new automatic base workflow.
- The keyboard button opens a typing fallback. Sending a typed message pauses
  voice capture to avoid overlapping requests; start listening again to return
  to voice. Failed text remains available for retry.
- Microphone, captions, spoken-reply mute, engine selection, task recovery, and
  session exit remain available without returning to the normal chat layout.

The interface supports light/dark themes, narrow and landscape screens, safe
areas, keyboard focus containment, and reduced-motion preferences. Its animated
presence is phase-based; it is not an audio-amplitude meter.

Pipecat is now available as an optional CPU streaming backend. See
[Pipecat voice](pipecat-voice.md) for installation, voice choices, and the
execution boundary. Classic and cloud engines remain selectable; cloud voice
retains its billing.

## Verification

Unit/integration tests cover transcript replacement, speech-state priority,
history navigation, typed fallback recovery, native preview keyboard handling,
and inline generation review. The fixture-only browser audit can be run with:

```powershell
$env:DARIUS_PLAYWRIGHT_MODULE = 'C:/path/to/node_modules/playwright'
$env:DARIUS_UI_URL = 'http://127.0.0.1:3000'
node scripts/check-fullscreen-voice.cjs
```

The audit uses generated silent audio and intercepted API responses, never a
real microphone, model call, or render. Screenshots go to
`data/fullscreen-voice-audit` and cover both themes at phone, tablet, desktop,
and landscape sizes. It is not a real-device speech-latency or echo test.
