# Reproducible application checks

The `Application checks` workflow runs backend, OpenAPI, privacy and frontend
checks on pull requests and pushes to main. A separate Windows job runs on main
pushes and manual dispatches; it installs the locked dependencies into a fresh
runner and exercises installer safety, empty-database migration, previous-schema
upgrade and a Windows web build. Pull requests run the faster Linux jobs.
`release-checks` aggregates their results and fails if a required job fails or
is cancelled. Configure that status as a required repository check, and require
a successful main/dispatch run including Windows before publishing a release.
This file does not change GitHub branch protection settings.

## Clean checkout

Use Python 3.12, uv 0.11.19 or newer, Node.js 24, and Git. CI pins uv 0.11.28. No `.env`, model,
ComfyUI, provider key or voice runtime is needed. Do not copy a workstation's
settings or database into the checkout.

```sh
uv sync --frozen --extra test --python 3.12
uv run --frozen pytest -q
uv run --frozen python scripts/export_openapi.py --check
npm ci --prefix apps/web
npm run lint --prefix apps/web
npm run typecheck --prefix apps/web
npm test --prefix apps/web
npm ci --prefix tests/browser
npm --prefix tests/browser run install:browser
```

Build with `DARIUS_NEXT_DIST_DIR=.next-check`, then run
`npm --prefix tests/browser test`. In PowerShell:

```powershell
$env:DARIUS_NEXT_DIST_DIR = '.next-check'
npm run build --prefix apps/web
npm --prefix tests/browser test
```

On Linux use `DARIUS_NEXT_DIST_DIR=.next-check npm run build --prefix apps/web`.
Minimal Linux runners also need browser system dependencies:
`npm --prefix tests/browser exec -- playwright install --with-deps chromium`.
The pinned Playwright package fixes the matching browser revision. Its setup
follows the [official CI guide](https://playwright.dev/docs/ci).

On Windows, `scripts/check-reliability.ps1 -Browser` runs the application checks,
isolated build and browser suite in sequence after dependencies are installed.
Add `-Privacy` in the clean public checkout to run the existing history/privacy
audit. Failures stop the script; do not prepare a ZIP or push a release until the
checks pass. Existing `prepare_release.py` also retains its own privacy gate.

## What these checks establish

- Browser: six journeys at desktop and phone widths, isolated state per case,
  explicit fixture responses, blocked unexpected network access, runtime errors
  treated as failures, and traces on failure. No live API or render is needed.
- Migration: a temporary database at the historical multi-board schema receives
  synthetic project/chat/board data, upgrades to head twice, and retains its
  content and seed. Empty installation checks all declared table/column names.
- Windows: dependency installation/build plus existing manager tests for config
  preservation, process ownership, refused unsafe updates and failure recovery.
  This does not automate WinGet elevation dialogs, GPU drivers, ComfyUI/model
  installation or a real voice session. Those remain manual release acceptance.
- Publication: the existing audit checks the clean source tree and full fetched
  history. Reports and caches stay ignored; the demo assets remain separately
  reviewed. No private runtime files are uploaded as CI artifacts.

Automation provides repeatable regression coverage; real generation quality and
hardware fit still require deliberate live validation. Local and CI results
should be reported separately until the workflow has actually run on GitHub.
