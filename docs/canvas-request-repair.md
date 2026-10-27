# Canvas overview Generate request repair

Fixed the reported `Alien: [object Object],[object Object],[object Object],[object Object]` failure.

The overview passed its entire saved generation intent to `canvasApi.generate`. A spread added during profile support sent four internal fields (`documentId`, `documentRevision`, `name`, `key`) alongside the generation API fields. The strict backend correctly rejected them with four HTTP 422 validation objects before any ComfyUI work was queued. The shared client assumed `detail` was a string, so the objects became unreadable text in the board error.

The generation API client now explicitly serializes only `boardId`, `boardRevision`, optional `profileId` and optional `promotedFromGenerationId`, alongside its separately supplied revision, request key, seed and approval. Caller context cannot override those arguments or add bookkeeping fields. This preserves strict backend validation and applies equally to MOSS, FIBO, focused generation and historical promotion.

Shared HTTP, upload and initial streaming-error handling now formats standard validation arrays with field paths and messages, unwraps nested detail/message errors, and uses a readable fallback for unknown structures. Rejected `input` and `ctx` data are not dumped into the UI.

Verification:

- Reproduced the exact four validation objects against the live endpoint using `approved=false`, so the diagnostic could not start a render.
- Regression tests cover a full overview intent, authoritative revision/seed/approval arguments, promotion metadata, large seeds and uncertain-transport retry identity.
- 252 frontend tests, TypeScript and the production build passed; changed-file lint passed.
- The real overview Generate button completed one render of an isolated copy of the saved Alien composition. Its actual API payload contained only supported fields, returned HTTP 200, and collected one final image. A separate simulated HTTP 422 verified readable field messages in the same UI while retaining the prior result.
- The verified frontend build was published. Backend model setup, database and worker code did not need changes.

Artifacts: `data/canvas-generate-repair/browser-report.json`, `overview-render-completed.png`, `structured-error-readable.png`, and `deployment.json`. The opt-in browser check is `scripts/check-canvas-request-repair.cjs --run`; it refuses a second live submission if a saved job already exists.
