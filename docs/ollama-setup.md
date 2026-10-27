# Optional local chat with Ollama

After **Install / repair**, stop Darius and choose **Install local AI** in
`install.bat` or `Darius.bat`. It installs missing Ollama using the official
`Ollama.Ollama` WinGet package and downloads the public
[`ornith-1.5:9b`](https://ollama.com/library/ornith-1.5:9b) model. The published
Q4_K_M model and vision projector currently total approximately 6.6 GB. Allow
additional space for the Ollama application; the manager shows guidance before
the download. Model files are not included in the Darius ZIP.

16 GB or more system RAM is recommended. CPU-only chat can be slow. GPU memory
requirements depend on context length, offloading and other applications; a 9B
model being installed does not guarantee full GPU residency on every machine.
Darius's Ornith profile starts with a conservative 32K context unless you have
explicitly overridden it. Context can be adjusted in your local configuration.

The action reuses existing Ollama installations without upgrading them. It uses
the native loopback API at `http://127.0.0.1:11434`, starting a hidden local server
only if that endpoint explicitly refuses the connection. An unexpected HTTP
response or a timeout is reported instead of starting another server. Existing
services are not stopped. A server started here remains available after the
progress window closes; quitting Ollama is separate from **Stop Darius**.

Ollama downloads and verifies its own model layers. Interrupted downloads can be
resumed by running the action again. An already installed model is inspected
without pulling over it. Setup verifies its model family, size, quantization and
reported completion/tools/vision capabilities using metadata APIs. It does not
run a chat, tool call or image inference, and does not load weights onto the GPU.
Metadata verification is not an end-to-end chat or vision test.

After verification, choose **Yes** to select Ornith for Darius chat, or **No** to
keep the current provider. Selection backs up the local settings/database,
updates only the provider/model/local API address and saved chat selection, and
retains cloud keys and the existing OpenAI thinking preference. Start Darius
afterward. If selecting later, use **Settings → AI model → Ollama → Refresh
models**, then select `ornith-1.5:9b`.

For scripting, installation and selection are separate choices:

```powershell
.\install.bat -Action Ollama
# Explicitly choose Ornith after download and verification:
.\install.bat -Action Ollama -SelectOllama
```

Both require Darius to be stopped. The first command keeps the current chat
provider. Automatic selection supports Darius's local SQLite installation;
external database installations should select the model through Darius Settings.

## Manual alternative

Install Ollama from its [official Windows download](https://ollama.com/download/windows),
then open a new terminal:

```powershell
ollama pull ornith-1.5:9b
ollama list
```

Start Darius, refresh the Ollama model list in Settings and select the model.
For a custom Ollama endpoint, configure it in your local `.env` and restart
Darius. The optional installer action itself always checks the default local
port 11434. See [Ollama on Windows](https://docs.ollama.com/windows) for relocating
model storage with `OLLAMA_MODELS`, supported GPU drivers and Ollama logs.

## If setup fails

- **WinGet missing:** install Ollama manually from its official download, then
  repeat the action. No package source or executable URL is guessed.
- **API/port error:** ensure the service on port 11434 is native Ollama. Setup does
  not kill another listener or treat an HTTP error as a stopped server.
- **Disk space:** free space in Ollama's model storage location, or set
  `OLLAMA_MODELS` consistently for the daemon and setup process, then retry.
- **Wrong/older model metadata:** inspect the installed model and Ollama version.
  Update Ollama manually if necessary; the installer preserves existing models
  and does not overwrite a customized tag to force a match.
- **Download interruption:** rerun **Install local AI** to resume. Your chat
  provider is retained unless you explicitly select Ornith after verification.

Progress logs are under private `data/setup-logs`. Do not share `.env`, model
credentials or private database backups.
