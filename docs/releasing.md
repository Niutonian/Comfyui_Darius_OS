# Release preparation

Darius is currently an early-access Windows application. Publish a reviewed source snapshot, not the contents of the development workstation.

For transfer/install checks, follow [SECOND_MACHINE_TEST.md](../SECOND_MACHINE_TEST.md). The owner tested v8 and selected 0BSD for original Darius code. Workflow and model attributions are in [ATTRIBUTIONS.md](../ATTRIBUTIONS.md); the coverage-preserving regression migration is documented [here](regression-migration.md). Publish only after the complete validation and privacy checks pass.

## Repository boundary

The root `.gitignore` excludes environments, builds, databases, generated media, weights, credentials, personal LAN trust artifacts, local design/demo workspaces and per-job workflow graphs. Reviewed static contracts are explicitly allowed. Keep application code, migrations, tests, lockfiles and versioned Canvas templates in Git.

The separate `recast/` experiments workspace is excluded in full, including its nested environments, archives and reference media. The exporter also rejects this directory independently of Git ignore rules. Its local contents must stay intact.

Ignoring a previously tracked file does not remove it from the index. Use an explicit `git rm --cached` only for files that should become local; this preserves their working copies. The cleanup removed local design assets and session handoffs from the index. Those assets remain in earlier commits; no history rewrite was performed.

Keep development originals immutable. The source-only release exporter applies the versioned `workflow-metadata-privacy-v1` policy to known authoring metadata, records before/after hashes, and updates the release copy's source UI manifest checksum. It verifies executable API/template bytes remain identical. Rendering changes still require a new adapter/template version. Review provenance and upstream redistribution terms before publication.

## Verification

Follow the setup and validation commands in the root README. Run `python scripts/release_audit.py --history --privacy` to inspect candidate files and historical text blobs for recognized credential patterns, oversized files and tracked ignored files. Privacy mode also flags local artifact paths, current workstation paths and private artifacts retained in history. It prints locations, never matched credential values. This is a heuristic scan, not proof that a repository contains no secrets or personal information.

## Privacy checkpoint — 2026-10-24

The deep review found no tracked, candidate or historical `data/` files. All 8,699 data files checked individually were ignored, including screenshots, projects, backups, diagnostics and model/checkpoint files. Four previously tracked documentation screenshots under `docs/ui-review/` were also removed from the index, preserving their local files. Screenshot, recording, backup, browser-report and export ignore rules were strengthened.

**The development repository stays private.** It retains 65 private artifact paths in history (older design assets/screenshots and session handoffs/status). Five original H3 authoring/export files contain workstation paths. A passing credential-pattern scan alone is not a privacy clearance. Publish only a validated, source-only release repository.

The release exporter resolves those publication blockers by copying eligible source into a separate Git repository, stripping the known metadata fields and transferring the optional R2T2 gitlink without its installed checkout. It never copies development history, Git configuration, hooks, credentials, runtime data or dependency/build directories. It creates no commit, remote or push. Local originals and development history remain available. Detailed local inventories stay under ignored `data/release-cleanup/`.

## Prepare a private preview

```powershell
.\.venv\Scripts\python.exe scripts/prepare_release.py .tmp/releases/darius-private-preview
```

Choose a new destination for each run; existing folders are never replaced. The exporter stages the sanitized source and `release-provenance.json`, then requires the privacy audit to pass. Inspect that repository for all subsequent publication steps. Do not push the original development repository.

Install locked dependencies in the preview, run all checks below, and review the staged source. Generated databases, environments and build artifacts remain ignored there. If source changes after export, create another preview; the receipt hashes describe the copied source at export time. Public publication also requires the owner's license/redistribution decisions; technical validation does not grant third-party rights. See `THIRD_PARTY_NOTICES.md`.

For a clean-checkout test, include both tracked source and new application files intended for the release, excluding ignored workstation files. Install with `uv sync --frozen --extra test` and `npm ci --prefix apps/web`. Use a fresh environment and database, run Alembic migrations, the backend tests, OpenAPI drift check, frontend tests, lint, typecheck and production build. Never copy a developer `.env`, database, media directory or frontend build into that checkout.

Normal automated tests do not need paid generation calls or GPU renders. Test ComfyUI separately using the documented Canvas recipes and a compatible local installation. Optional R2T2 source can be initialized with the submodule command in README; CPU voice does not require it.

## Publication decisions

- Review the final staged diff and run the audit again after staging.
- Original Darius code is 0BSD under the owner's license choice. Model weights, optional runtimes and third-party workflow templates retain separate terms; consult ATTRIBUTIONS.md and THIRD_PARTY_NOTICES.md.
- Configure the intended Git remote before pushing. No remote was configured at cleanup time; no push was performed.
- Use a private repository if publication and licensing decisions are still pending.
- Keep the app on trusted devices/LAN. Project identifiers are not a public multi-user authentication boundary.

Commit and push only after validation and publication review. Do not rewrite existing history or remove local project data as part of routine release cleanup.
