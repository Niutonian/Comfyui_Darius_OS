# Live project synchronization

Implemented 2026-10-18. Devices must connect to the same Darius server/database, preferably through the existing trusted LAN HTTPS address.

## What synchronizes

Saved conversation messages, chat names/list/deletions, project details, assets, job status, trusted-workflow selections, production characters/scenes/shots, execution permission, project context and saved timeline versions. A freshly opened project selects the most recently active chat; an already-selected conversation stays selected on that device. An empty open project can receive its first remotely-created conversation.

One project-scoped EventSource connection per browser drives coalesced canonical reads. It does not start AI replies, generate media, or consume model tokens. Completed replies appear on other devices once persisted; token-by-token streaming remains on the originating device.

The stream starts at the current event watermark rather than replaying years of history. A ready barrier triggers a fresh snapshot; reconnects use Last-Event-ID and refresh again. Changed job snapshots trigger invalidation; identical one-second heartbeats do not. Visible online tabs reconcile every 15 seconds as a backstop, and immediately after focus/network/visibility recovery. EventSource-unavailable browsers retain periodic synchronization. A top-bar indicator reports the event connection, not a guarantee that every individual read succeeded.

## What stays local

Unsent composer text, open panels, navigation, selected chat, microphone/wake-word state, voice playback and full-size asset presentations stay on their originating device. A remote reply must never activate a microphone, speak, open media, or trigger another assistant call. Switching the selected chat is not forced on other devices. Browser drafts are not durable cloud drafts and do not transfer between devices.

Production record editors keep their local input state. Open project-context forms adopt remote changes only while clean; dirty forms show a notice. Clean timeline editors advance to newer saved versions; dirty cuts remain intact and show a load-latest/save-separate-version choice. Loading over a dirty timeline requires explicit confirmation. New version summaries record their base version. This is saved-data synchronization, not character-level collaborative editing or automatic field merging. Explicit simultaneous saves of ordinary records still use existing server semantics.

## Verification

- `tests/test_device_sync.py`: isolated databases, separate clients, initial watermark, event resume, project scoping, remote rename/delete.
- `apps/web/src/lib/project-sync.test.ts`: burst coalescing, unchanged heartbeats, reconnect/focus, fallback, cleanup.
- Chat regressions: remote history, initial chat, rename, no presentation/model replay, existing streaming behavior.
- Editor/context regressions: clean refresh and unsaved-change preservation.
- `scripts/check-device-sync.cjs`: two isolated Chromium desktop/phone contexts with a shared fixture HTTP API and real persistent SSE. Verifies phone send → desktop reply, remote rename, dropped-stream recovery, retained desktop draft, no remote model/media side effects. No user-project writes, model requests or real renders.
- Real LAN gateway: certificate-validated HTTPS live-event endpoint returns ready + job snapshot without historical replay.

Build compilation and TypeScript checks passed. Selected backend suite: 40 passed. The full frontend run had 131 passed and one unrelated existing call-shape assertion in `llm-setting.test.tsx`: the implementation passes an optional third `undefined` argument for non-OpenAI providers, while that assertion expects exactly two arguments. No model-settings implementation or tests were changed for this task.

Deployment restarted only the idle API and web processes. ComfyUI, model servers, voice sidecars, gateway and firewall configuration were untouched. Existing browsers need one reload to load this new client; subsequent saved project changes synchronize automatically.
