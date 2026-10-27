# Shot production board

Open **Create → Shots**. The board groups existing shots across scenes, with
scene/status filters, pinned image references, linked takes, chosen media, and
tracked render jobs. Use **Manage scenes & shots** to create or edit records.

- Pin up to four project images as shot references.
- Link existing image/video media as takes without moving it out of the library
  or changing ownership. Choose a take to save the existing shot selection.
- Readiness is a deliberate production decision. Job completion alone does not
  change it. Selected/complete require a chosen take.
- **Work with Darius on this shot** saves the active scene/shot and references,
  preserves other project notes, replaces previously selected reference images,
  and opens Talk. It does not start a render.
- New queued manual generations snapshot the active shot at queue time. Local
  assistant renders use the shot snapshot saved with the originating user
  message, so changing focus later cannot reassign that render. Retries retain
  their original job payload. Outputs appear on that shot automatically.
- Historical media without a shot association can be linked explicitly. The
  board does not guess associations by filenames or pull media from other projects.

Links persist in the additive shot_production table. The matching Alembic
migration is e83d4f2b051a; local startup creates missing tables. Existing shot,
asset, job and workflow records are preserved. Project deletion removes its board
links together with its shots.

Offline checks: tests/test_shot_board.py, the frontend board tests, and
scripts/check-shot-board.cjs (fixture-backed browser checks; no model calls or renders).
