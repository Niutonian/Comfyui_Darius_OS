# Reliability checks and recovery

## Voice
Settings → Voice → **Fast device voice** uses installed English Windows voices on the Darius server. WAV audio is played through the browser's already-unlocked AudioContext; it does not depend on browser speechSynthesis events and does not consume GPU VRAM. Choose the voice in the same panel. OmniVoice remains available and is tried if Windows synthesis fails.

Use **Test microphone**, **Test speaker**, and **Check service** before starting Talk. Microphone testing stops after five seconds. Speaker diagnostics use the same synthesis and playback path as replies. Check the browser tab and output-device volume if playback completes silently. Final transcription is still CPU Whisper (Vosk supplies live drafts); cloud voice is unchanged.

Speech failures leave the text reply intact and return the microphone to listening. Muting stops playback, and ending a session ignores late replies. Automated tests cover three consecutive spoken turns, fallback, timeout, cancellation, and muted turns. Real microphone acoustics/output routing still need a human check.

## Saved tasks

Render authorization uses the same intent rules as routing. Visual constraints
such as “without people” and “only one shot” do not revoke generation permission;
writing scenes, questions, workflow/prompt authoring and explicit no-render
instructions do not authorize execution. Explicit same-prompt workflow tests
retain the previous user brief and count; vague approvals never replay queued work.

Manual chat review now records the source message and project-checked conversation.
Approval is transactional and idempotent per action plan. Its job, completion and
original chat receipt stay linked; the earlier draft reply remains available as
history. Existing unlinked jobs are not retroactively reassigned.

The shared recipe preparation path can omit unused Qwen autogrow reference tails
only when the installed schema confirms they are optional. It never duplicates a
reference or substitutes a saved example. Explicit image aspect ratios/dimensions
select an existing supported canvas (including the Qwen canvas switch); the review
shows its dimensions. Unsupported/ambiguous canvases stop before queueing with an
actionable explanation. Base workflow files, model choices and project isolation
are unchanged. These adapters apply to every chat model using the shared bridge.
Pause stops at the next model/tool boundary; it cannot interrupt a request already in flight. Resume continues the saved checkpoint. Cancel prevents future steps and requests cancellation of an associated active render. Rendering cannot be paused; use Background jobs to cancel it. Cancelled requests cannot be resumed—send a new request.

After API restart, unfinished planning is marked interrupted (or paused if requested). Reopen the conversation and choose Resume saved task. Checkpointed tools are not replayed after successful completion, and render queueing retains its one-job-per-message guard. In-flight operations at a crash still rely on their own idempotency.

## Project context
Talk → **Project context** saves notes, active character/scene/shot and up to four pinned image references. Explicit message attachments take priority. Select project images, choose Pin selected project images, then Save context. These preferences are stored in the project database, not shared across projects.

Foreign story records, reference assets, and generated workflows are rejected at ownership boundaries. Shared workflow templates remain available. New drafts must bind template image loaders; earlier tool uploads cannot justify unrelated saved example images.

## Regression suite
Run from the repository:
```powershell
./scripts/check-reliability.ps1
```
This runs the backend tests, committed API-contract check, frontend tests, and production build. Job lifecycle integration tests use isolated fake providers and fixture graphs, independent of installed ComfyUI workflow files. No paid APIs or real renders are used.

For browser layout checks, start the freshly built frontend and run:
```powershell
./scripts/check-reliability.ps1 -Browser -UiUrl http://127.0.0.1:3000 -PlaywrightModule C:/path/to/node_modules/playwright
```
The browser suite intercepts all API calls with fixtures. It checks all six views, light/dark, 390/768/1440px widths, composer bounds, Production Bible input bounds, and the inspector/jobs controls. Screenshots are saved under ignored `data/ui-audit/`. Playwright and Chromium must already be installed; this script does not download them.

Live model, ComfyUI and microphone checks are separate, deliberate tests because they can consume resources or create media. A green simulated suite does not establish live model quality.

For an optional **local speaker-only** smoke, set `DARIUS_LIVE_VOICE=1` when
running `node scripts/check-ui.cjs` against port 3000 with the voice service
running. This adds a real Windows WAV synthesis/decode/playback check while
keeping project and model APIs mocked. It does not record the microphone.
