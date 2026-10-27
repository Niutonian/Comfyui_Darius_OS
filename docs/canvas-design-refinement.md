# Canvas design refinement — 23 October 2026

Implemented the behavior in `data/screenshots/DARIUS_CANVAS_DESIGN_UPDATE.zip`, after reading its handoff and inspecting both proposed mockups. The existing stack is Next.js 16 / React / TypeScript with the existing OS shell, Canvas/Konva editor and shared project conversation. The concept PNGs are reference material only; the application displays actual stored artwork and state.

## Result

- Canvas expands within the existing OS shell by default. A compact application bar and one toolbar replace the large headline/window padding. Restore-window and Back to Library retain access to the rest of Darius. Expansion changes presentation, not saved world coordinates.
- Board, Chat and History share a single reserved utility panel, 320–380 CSS pixels on desktop. Switching views does not stack inspectors or submit actions. The existing conversation/composer are hosted once; the chat header explicitly identifies the board, and voice controls remain available in the panel. Existing captured message targets are unchanged.
- Cards have a dedicated header and footer, leaving the image area unobstructed. The contained image/backdrop strategy remains. Fit-to-artwork now accounts for card chrome. At distant zoom, identity/status labels compensate for the workspace scale and secondary controls disappear. Generate remains disabled under the existing preparation/job rules. A visible older image during an active run is labeled as the previous result.
- The focused editor uses an in-flow tool rail, measured artboard area and the same docked utility panel. Region controls, hierarchy and history no longer float over desktop artwork. Layout, Result and Overlay correspond to actual existing rendering flags; a draft without an image is identified as Layout. Provenance shows result and layout revisions, with expandable guidance that moving guides does not move pixels.
- Phone layout keeps the board browser. Utilities become one dismissible, focus-managed view within the Canvas body; opening application navigation dismisses that view. Toolbars scroll explicitly where needed, the Generate action fits, and closing utilities exposes an artwork-only editing area. The existing visual-viewport handling continues to size the UI around the keyboard.

Manual pan/zoom is not reset on field changes or panel changes. Fit uses the space remaining after the panel and tool rail are laid out. Drafts, region selection, board IDs, archives, saved layout, original assets and execution paths are retained. No scheduler, workflow adapter, image-conditioning path or downstream auto-run behavior was introduced.

## Changed components

`create-view.tsx` owns the existing-window expansion preference. `moss-workspace.tsx` supplies Board/History contents, compact toolbar/status and independent card gestures. `canvas-workspace.tsx` supplies the existing region/hierarchy/history contents and real view modes. `canvas-utility-panel.tsx` provides the shared panel, accessible tabs, mobile focus/dismissal and conversation hosts. `canvas-refinement.css` scopes the presentation changes; theme tokens and the established editor/state APIs are reused. The card fitting helper includes the header/footer allowance.

## Verification

- Full web suite: **244 tests across 58 files passed**. Includes the existing captured-board chat race, independent drafts, request identity, focus continuity, project navigation and the new no-image display-mode check.
- Typecheck, scoped ESLint and production build passed. The existing Next build warning about Node localStorage remains non-blocking.
- `scripts/check-canvas-design.cjs` passed against both preview and the deployed LAN HTTPS production build: 1920 × 1200 light, 1440 × 900 light/dark and 412 × 915 phone. Checks cover reserved panel geometry, explicit chat target, one composer, retained voice controls, tab switching without submissions, independent dragging, undo, readable distant labels, window restore/expand, fit bounds, region editing without recentering, return/reopen/reload, keyboard tab navigation without region movement and a reduced-height phone viewport. Layout/document writes in these browser checks are isolated fixtures; no real user documents are edited. Native Android IME interaction was not directly automated.
- **Three real local MOSS renders passed** in the isolated acceptance database: A rendered while B queued at shared capacity one; C remained editable/focused; browser reload retained the correct board; A's next result did not update B's pinned version. Red cube and blue sphere outputs were visually inspected. Model layout adherence remains advisory rather than a guarantee of pixel-perfect bounds.
- The explicit visual-reference picker, update confirmation, pinned preview and undo/redo passed with **zero cascade generations**.

Evidence: `data/screenshots/2026-10-23-canvas-design/browser-report.json`, `data/canvas-design-acceptance/generation-report.json` and `reference-ui-report.json`. GPU acceptance project: `b7d2e451-b9a9-4c42-8124-6599a798983a`, in `data/multi-board-acceptance/darius.db`, not the live project database. The original MOSS workflow master hash remains `2077e236a84a8518e4614a35f7cb52b2a1b953da226c51eee02246e89f08ca0d`.

Before screenshots: `data/screenshots/2026-10-23-canvas-browser-review/`. After screenshots: `data/screenshots/2026-10-23-canvas-design/live/`, captured from the actual deployed UI without editing documents or submitting generations. The browser-check screenshots alongside `live/` include fixture-only edit names and should be read as test evidence, not additional real project revisions.

## Deployment and limits

Deployed the production web build and restarted **only web port 3000**. API, main workers, ComfyUI, voice and LAN HTTPS remained running. No database migration or model/provider setting change was required. Previous web build: `data/backups/canvas-design-20261023-142654/web-next/`. Temporary preview services and the isolated test worker were stopped after their queue completed; reports and assets are retained.

A new minimap is deferred. This pass remains MOSS text-to-image: visual notes pin exact versions and do not condition images or trigger linked renders. No I2I/video path or new editing engine was added. Extremely small overview cards necessarily truncate titles; the full identity/actions remain available through selection, search and the utility panel. Card dimensions retain the existing presentation bounds.

## Resize handles and visible duplication follow-up

Resize controls now live in a separate screen-space Konva layer above every region. Their visible size stays stable when zooming; the invisible grab target is 26 CSS pixels for mouse and 40 for coarse/touch pointers. Transformer events cannot fall through to the stage's region-picking handler, including when the handle is outside the region or overlaps a later-drawn region. Existing geometry normalization, bounds, locks and undo semantics remain unchanged.

Each desktop card has a Copy icon, and the Board panel has a prominent **Duplicate board** action accessible on phones as well. Both reuse the existing independent-copy endpoint and save preparation. Copies have their own document ID, prompt/regions/settings and empty generation history; creating a copy does not submit a render or move the original boards. Desktop duplication brings the new copy into view.

Verified the full 244-test web suite, typecheck, scoped ESLint, production build and the backend duplicate-isolation test. Real-browser checks passed in preview and on the deployed LAN HTTPS app: all eight anchors grabbed outside their visible square at three mouse zoom levels and with emulated native Chromium touch events (32 resize cases), including a later overlapping region; geometry, undo, retained selection and closed phone settings sheet were checked. Desktop card and phone panel duplication each submitted one correct copy request without render calls. Live document writes in these interaction tests are isolated browser fixtures. The existing four-viewport Canvas design checks also passed. Evidence: `data/screenshots/2026-10-23-canvas-resize/browser-report.json` and accompanying screenshots. Physical Android hardware was not separately exercised.

Only web was restarted for this follow-up; previous build: `data/backups/canvas-resize-20261023-174943/web-next/`. No API/database migration was needed.

## Generation feedback and status polling hotfix

The reported Paris-copy request (`d70a9f6b-02cc-4280-baed-977894852c0a`) was accepted and completed. During its output ingestion, workspace status requests failed with SQLite `database is locked`: the GET route unnecessarily acquired `BEGIN IMMEDIATE`. Clearing local Preparing after acceptance could therefore expose the previous cached Ready receipt. The compact-card rule also hid action footers regardless of selection or active work, and request errors could be hidden in collapsed card copy.

Initialized workspace polling now uses a deferred, consistent WAL read transaction. Only the lazy document-to-board mapping path acquires the write lock, rechecking after acquisition. A new regression holds an uncommitted output writer and verifies an existing workspace still returns the committed Running receipt promptly; newly added documents still map correctly.

The frontend caches an accepted Queued/Running receipt before clearing Preparing. Selected, active and failed compact cards retain their actions; the Board panel provides Generate/Retry independently of overview zoom. Rejected submissions show Needs attention plus visible error text. Status outages are identified as showing last-known data. A completed unselected result is labeled New result instead of silently presenting the older selected image as the whole story. Captured request IDs and backend idempotency rules are retained.

Verification: **89 backend regression tests**, **244 web tests**, typecheck, scoped ESLint and production build passed. Browser feedback tests passed on preview and deployed LAN HTTPS for deferred preparation, accepted receipt retention during a polling outage, Queued/Running/Ready transitions, unchanged viewport, retained compact actions and visible HTTP 422 rejection, with one submission per case and no real render calls. Evidence: `data/screenshots/2026-10-23-canvas-status/feedback-report.json`.

One additional real UI render completed in the isolated acceptance project, with its matching active result and single output verified after reconnecting. Its initial harness failed after acceptance because it used a Fetch-only method on a Playwright response; the assertion was fixed and the accepted result was verified without generating again. That capture interruption is recorded in `data/canvas-status-acceptance/live-status-report.json`; active-phase/outage behavior is separately established by the fixture browser tests and held-writer regression, rather than claimed from the completed screenshot.

Deployed API and web with no schema or model/provider changes. Saved project/document/revision/board/model-preference hashes matched the verified database backup. The existing main render worker, ComfyUI, voice services and HTTPS gateway remained running. Backup: `data/backups/canvas-feedback-20261023-200223/`. Isolated test services were stopped after their queue completed.
