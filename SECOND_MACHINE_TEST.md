# First-version machine test

The owner has tested v8 on another machine. Original Darius code is licensed under 0BSD; third-party terms and attributions are recorded separately. This checklist remains available for later installations and release acceptance testing.

## Install into an empty folder

Recommended: extract the complete release, double-click **install.bat**, choose
**Install / repair**, then **Configuration** and **Start Darius**. Reopen using
**Darius.bat**. Test **Check installation**, **Stop Darius**, and a second
Install / repair run: settings and projects must be preserved. The unpublished
source candidate has no upstream; **Update Darius** must refuse safely.
See [Windows manager](docs/windows-manager.md). Manual setup follows below.

Use Windows 11, PowerShell, Python 3.12, uv, a Node.js version supported by Next.js (at least 20.9), npm, FFmpeg and ffprobe. Extract the source ZIP to a new folder; do not copy your development `data`, `.env`, environments, models, browser profile or builds.

```powershell
uv sync --frozen --extra test
Copy-Item .env.example .env
npm.cmd ci --prefix apps/web
Copy-Item apps/web/.env.example apps/web/.env.local
.\.venv\Scripts\python.exe -m alembic upgrade head
.\start-darius.bat check
```

Edit the new `.env` for this machine. Configure a local conversational model or your own cloud key. The example ComfyUI paths are placeholders: replace them with this machine's ComfyUI directories and Comfy MCP executable. Existing projects and credentials are deliberately absent. Without a configured model, the interface can open but chat cannot reply; without ComfyUI and the selected recipe's nodes/weights, local rendering is unavailable.

```powershell
.\start-darius.bat
```

Open `http://127.0.0.1:3000`. The launcher builds the frontend and starts local services. Keep its `data` logs if startup fails. Test ports must be free or belong to this checkout; do not stop unrelated services to make space.

## Things to check

1. Create a new project. The chat welcome orb should be centered. Rename a conversation, reload, and confirm the project and conversation remain available.
2. Configure the AI provider in Settings. Ask for ideas, then a text-only prompt. Neither request should submit a render job. Test a longer discussion and a correction to an earlier idea.
3. Open Fullscreen chat. Type without enabling the microphone. Save a reviewed idea, open Create → Ideas and reload. Copy, search, archive and restore it.
4. Add a Canvas board. Use in board should apply only its reviewed prompt, preserving the mode, resolution, references and seed. Undo the transfer. Generate explicitly from the board after its recipe is ready.
5. Test one supported image recipe and one H3 video recipe with your own installed nodes/models. Check the final preview, history, dimensions, duration and generated audio. A missing dependency should produce an actionable message rather than use another workflow silently.
6. If needed, install CPU voice separately using `scripts/setup-pipecat.ps1` and the documented model download steps. Test permissions, transcription, replies and continuing the conversation. Voice models/environments and the optional R2T2 checkout are not bundled in the ZIP.
7. For a phone or another LAN browser, follow `docs/lan-https.md` using newly generated trust material for this machine. Confirm saved ideas/project changes refresh across devices.

Report the failing step, browser, Windows/Node/Python versions and relevant diagnostic-console or `data` log excerpts. Inspect logs for keys or personal text before sharing them publicly. Your test results are the publication gate; do not run a push as part of this checklist.

## Automated checks

The normal commands are in README and `scripts/check-reliability.ps1`. Chat-denial, Canvas generation and historical worker/recovery coverage are described in [the regression migration map](docs/regression-migration.md). Run the complete suite before publication; a passing frontend build or privacy audit is not a substitute for backend regression checks.
