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

For the portable browser smoke suite, install its pinned tooling once:
```powershell
npm ci --prefix tests/browser
npm --prefix tests/browser run install:browser
./scripts/check-reliability.ps1 -Browser
```
The wrapper builds into `.next-check` and Playwright starts its own frontend on
loopback port 3100. It never reuses port 3000 or starts a backend. All API calls
are fulfilled by synthetic fixtures; unexpected APIs and other origins fail the
test. The twelve desktop/390px phone cases cover project creation, reviewed
prompt transfer without rendering, lost queue acknowledgement/receipt recovery,
completed result display, Qwen Edit thumbnail selection, a fullscreen chat turn, and video recovery without rendering. Traces from failed cases
stay under ignored `test-results/browser`. This small suite does not claim to
cover every layout, real microphone, provider, or workflow.

For individual commands, CI parity and the Windows installation smoke boundary,
see [release checks](release-checks.md). Before preparing a public release, run
`./scripts/check-reliability.ps1 -Browser -Privacy` from the clean publication
checkout. Privacy checks include tracked files and reachable history; do not run
publication preparation from the private development repository.

Live model, ComfyUI and microphone checks are separate, deliberate tests because they can consume resources or create media. A green simulated suite does not establish live model quality.

## Concurrent Canvas queue writes

Workflow registration skips unchanged records, including their timestamps. Canvas
image/video/composition requests register only their new immutable workflow;
worker startup and explicit catalog refresh can still synchronize the full catalog.
Pending changes are rechecked under a SQLite writer reservation so concurrent API
and worker registration cannot insert the same definition twice. SQLite connections
allow up to 30 seconds for brief writer contention to clear.

A Canvas request that still encounters a SQLite busy/locked error returns an
actionable 503 response. Retry the saved request with its original idempotency key;
an existing generation is reused. It does not automatically submit another render.
`tests/test_workflow_registration_concurrency.py` covers an unchanged catalog while
a worker holds the writer lock, overlapping registration from separate engines,
parallel board submissions and saved-request retries. These tests use isolated
databases and mocked generation services.

## Canvas acknowledgement recovery

Canvas submission now has a 45-second acknowledgement deadline, longer than the
30-second SQLite contention allowance. Network loss, timeout, throttling and
server failures retain the original intent key in the tab session. These are
uncertain outcomes, not evidence that generation stopped. A read-only,
project/document-scoped receipt lookup runs after an uncertain result and before
resubmission of a saved intent. Finding a receipt returns that same job without
launching a worker; an explicit retry with no receipt reuses the original key,
revision, seed and board inputs. Definitive validation/auth/conflict failures
release the intent so the user can correct the request. Closing setup does not
submit or automatically retry a render.

Regression coverage: `canvas-api.test.ts`, `test_moss_workspace.py` and
`test_workflow_registration_concurrency.py`. No real renders are required.

Duplicating a board preserves its displayed size and places the copy 48 canvas
units down/right from its source, cascading past occupied origins. It retains the
current camera instead of jumping to a newly fitted viewport.


## Chat history loading under background activity

The project job-list query already returns the full project history. The desktop
no longer starts a separate query for every remembered job ID; persisted IDs are
retained, and project jobs still refresh through events and bounded polling.
This avoids repeated waves of historical/foreign-project job reads on reload,
focus and the 15-second reconciliation backstop.

Conversation-list and message-history reads use a 45-second deadline; ordinary
read/discovery requests retain their 20-second bound, and reply streaming retains
its separate deadline. A history timeout is labelled as a conversation-loading
problem rather than an interrupted model reply. Reload conversation retries the
saved history in place and clears the loading failure on success; it never sends
a message or triggers a model/render call. Browser fixtures seed 50 remembered
historical jobs and reject unexpected per-job reads.
