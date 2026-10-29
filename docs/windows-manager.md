# Windows setup and management

Double-click **install.bat** or **Darius.bat**. Both open the native Windows manager;
Python, Node and a browser are not required just to open it. Extract the entire
release first, into a writable folder outside Program Files or OneDrive. Release
ZIPs contain one top-level `Darius` folder; open the launcher inside that folder.

1. **Install / repair** checks uv compatibility (minimum 0.11.19). If missing or
   too old, it downloads a checksum-verified private uv 0.11.28 from Astral under
   `data/tools/uv`, leaving any system uv unchanged. Missing Node.js LTS, Git and
   FFmpeg are installed through Windows Package Manager. Windows may ask permission.
   uv manages Python 3.12; Darius packages come from `uv.lock` and
   `apps/web/package-lock.json`. The action creates missing environment files,
   applies database migrations and builds the website. It can take several minutes.
2. **Configuration** opens your backend `.env`. Set the ComfyUI output/workflow
   directories and Comfy MCP executable for this machine. Configure the AI provider
   here or in Darius Settings. Example paths are placeholders, not detected services.
3. **Start Darius** uses the prepared build, starts services and opens localhost:3000.
   Optional voice services are detected by the existing launcher. Another app using
   the required ports produces an error; the manager does not stop it.

Core installation also prepares Comfy CLI 1.17.0 in an isolated environment under
`data/tools/comfy-cli`, so the example `COMFY_MCP_COMMAND` path does not need a
manual replacement. An existing valid custom CLI command is retained. The tool
environment is separate from ComfyUI's Python/PyTorch/CUDA and Darius's API lockfile.
Configure the ComfyUI connection directly in a board's setup panel using
**Detect ComfyUI** or its folder and server-address fields.

Existing `.env`, frontend `.env.local`, projects, models and workflows are retained.
Before migrations or an update, settings and the configured SQLite database are
backed up under `data/backups/setup-*`; SQLite backups pass an integrity check.
External databases and custom SQLite URI options require a manual backup and are
not updated automatically. Backups include private settings: never publish them.

The manager requires Windows PowerShell 5.1 and Windows App Installer / WinGet.
If WinGet is missing, install **App Installer** from Microsoft Store or install
the four prerequisites manually and retry. If a tool installation asks you to
reopen the manager, do that before retrying. Setup leaves completed downloads in
the package managers' caches; retrying a failed installation is supported.
Current installation progress is shown in a separate console; logs are under
`data/setup-logs`. Closing that console cancels the action; run Install / repair
again to complete it. Do not run the old launcher while setup is in progress.

## Services and optional components

**Stop Darius** stops Python services and the Next.js process belonging to this
exact installation, including workers and installed voice services. Finish active
renders first: Stop is an explicit termination, not a graceful render cancellation.
It leaves ComfyUI, Ollama, llama.cpp and other installations alone.
Installation, repair, voice setup and updates refuse to run while Darius is running.
**Check installation** reports tool/configuration/build presence and checks local
HTTP responses for API, web and default ComfyUI port 8188. A responding ComfyUI
server does not prove a particular workflow's nodes and weights are installed.

**Console code** opens the correct diagnostic access-code file for this
installation's configured data directory. Choose No in its dialog to reset and
open a replacement. Resetting takes effect immediately in the updated API;
previous browser logins become invalid. The code is never printed to setup logs.
Windows UTF-8 BOM and UTF-16 text files are supported when reading an existing code.
For a LAN browser, use the code on the API server, not a different local install.

**Install CPU voice** reuses the isolated Pipecat installer and downloads its speech
assets. **Set up LAN HTTPS** reuses the Caddy setup; see [LAN HTTPS](lan-https.md)
for certificate trust and firewall setup on your other devices. These are explicit
optional actions, separate from core installation. ComfyUI, Comfy MCP, LLM weights,
GPU drivers and workflow-specific models/nodes remain separately managed. Core
installation makes no paid API calls and downloads no LLMs or ComfyUI weights.

## Updates

For a published Git clone, Stop Darius, then choose **Update Darius**. The updater
requires a clean working tree, a branch with a configured remote/upstream, and
history that can fast-forward. It fetches that remote, backs up local settings and
the SQLite database, fast-forwards and reruns installation using the updated script.
It never pushes, resets, stashes, chooses a remote, or resolves conflicts for you.
If setup fails after the fast-forward, the source remains updated; fix the reported
problem and run Install / repair. Database downgrades are not automatic.

A source ZIP cannot update through Git. Extract a newer reviewed release into a
separate folder, stop the old installation, back up its settings/database/media,
and migrate that private data deliberately. Keep the previous folder for recovery;
do not overwrite a running install. A first private release without an upstream
reports that updates are unavailable rather than inventing a download address.

For scripting, use `install.bat -Action Install`, `Darius.bat -Action Start`,
`Darius.bat -Action Stop` or `Darius.bat -Action Diagnostics`. These explicit
commands run directly without GUI confirmation. Exit code 1 means the action
failed. The existing `start-darius.bat`, `worker` and `check` commands remain
available for manual/development use; the manager is the recommended entry point.

For an explicitly backend-only update, stop Darius and run
`repair-backend.bat`. It syncs the frozen API dependencies, backs up the configured
database and runs migrations while retaining the existing frontend build. Use
full Install / repair for first installation or any update containing web changes.
The v5 → v6 process-inspection fix and v6 → v7 GPU/node-reuse fixes are backend-only.

**Install local AI** is an optional action, separate from Install / repair. It
installs missing Ollama and prepares Ornith 1.5 9B, then offers to select it for
chat. Existing providers are retained unless that offer is accepted. See the
[Ollama setup guide](ollama-setup.md) for downloads, hardware guidance, manual
installation and the explicit `-Action Ollama -SelectOllama` scripting option.

Package source references: [uv installation](https://docs.astral.sh/uv/getting-started/installation/),
[Node.js WinGet manifest](https://github.com/microsoft/winget-pkgs/tree/master/manifests/o/OpenJS/NodeJS/LTS),
[Git manifest](https://github.com/microsoft/winget-pkgs/tree/master/manifests/g/Git/Git),
[FFmpeg Windows builds](https://www.gyan.dev/ffmpeg/builds/).

See [private workspace backups and restore rehearsal](workspace-backups.md) for the manager backup/report actions, media exclusions, verified full copies and isolated restoration.
