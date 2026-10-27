# Local voice

For the new continuous CPU streaming engine, see [Pipecat voice](pipecat-voice.md).
The documentation below describes the **Classic local voice** fallback. Choose
it under Settings → Local conversation engine to use its wake-word controls.

The local speech service runs at `http://127.0.0.1:8002`, bound to loopback. It uses an isolated `.venv-voice` environment so speech dependencies do not change the API or ComfyUI environments.

## Using it

1. Open Talk and the settings icon next to the project-image button in the composer.
2. Enable **Listen for "Darius" locally**, and grant microphone access. Activation is deliberately per session; refresh, leaving Talk, and project changes release the microphone.
3. Say **Darius**, **Hello Darius**, **Hey Darius**, or **Hi Darius**. The status changes from wake listening to conversation listening. A request in the same utterance is supported.
4. Wait for each reply. Microphone frames are paused while Darius thinks and speaks, preventing its own voice from starting another turn.
5. Say **goodbye**, **stop**, or **end conversation** to return to wake listening. Uncheck the setting to stop all microphone access. **Start voice** enters conversation directly; **Interrupt & speak** stops playback and listens again.

Use Chrome or Edge on the local port-3000 page. The first browser microphone permission still needs a click. This implementation is English and requires Talk to remain open; browser background suspension can interrupt it. It is not a Windows system-wide listener. Each spoken turn is limited to 30 seconds. Recognition quality with the user's microphone and accent still needs an in-person check.

## What runs locally

Local voice preferences live in **Settings → Voice** and are saved in this browser:
pause-to-send duration, spoken replies on/off, and an optional OmniVoice voice
style. The **Spoken replies** switch is in Settings → Voice.
Disabling spoken replies does not disable dictation: the next turn listens
as soon as the assistant finishes its text reply. The style menu contains supported
English OmniVoice traits. Unsupported descriptions saved by an older version fall
back to the default voice. These styles do not lock a speaker identity or change
GPT-Live voices.

Spoken replies default to **Fast device voice**, which uses an installed local
English Windows voice on the Darius server without waiting for CPU OmniVoice generation.
Settings lists the server's installed English voices. Speech returns as WAV and
plays through Web Audio, without browser speechSynthesis. If Windows synthesis fails,
Darius tries OmniVoice. Select **OmniVoice** in Settings for its voice
styles and slower generated speech. The full assistant reply remains in chat.

Settings also includes microphone, speaker, and local-service diagnostics.
See [Reliability checks and recovery](reliability.md) for the offline regression suite.

An active local conversation keeps the same microphone session between turns.
Audio capture pauses during the assistant reply and playback to avoid echo. Speech
download/decoding has a 90-second CPU limit and playback has a duration-based watchdog;
failures return to listening. Continue listening skips pending speech preparation,
while Interrupt & speak skips playback. Leaving Talk or ending voice still releases
the microphone intentionally.

During an active conversation, Vosk also supplies a live draft on CPU. Completed
phrases stay in the draft while the next phrase is recognized; repeated identical
updates are suppressed. The preview follows new words unless you scroll up.
After the selected pause (1.2 seconds by default), the draft remains visible as
"Finalizing transcription" while the configured final recognizer runs. Only its
final text is submitted to the assistant, never provisional captions. Empty or
failed transcriptions clear the draft before listening resumes. This preview
requires no additional model download or GPU allocation.

- Vosk's small English model performs CPU streaming wake detection using a dedicated phrase vocabulary plus an unknown-word category. Ambient transcripts are never returned to the browser.
- After activation, the configured transcription provider handles the command. The default remains faster-whisper `base.en` on CPU/int8. With `TRANSCRIPTION_PROVIDER=r2t2`, active turns are sent to the local Confucius4-R2T2 WebSocket service while Vosk continues to handle wake detection and turn boundaries. R2T2 failures fall back to faster-whisper. Audio is transient, held in memory rather than recorded to files, bounded to 30 seconds and cleared between utterances.
- If R2T2 is selected but its service is offline, voice startup remains available through CPU Faster-Whisper. Health reports both the selected and active transcription providers; a new turn uses R2T2 again when its service becomes reachable.
- OmniVoice generates WAV replies locally. The browser plays these with Web Audio; it does not use browser speech recognition or browser speech synthesis as a fallback.
- The configured assistant AI still receives command text and the normal project context after activation. Wake listening itself calls no AI provider or paid service.

The WebSocket accepts the two local port-3000 origins only. Browser microphone capture is explicit. Requests carry a session epoch so late recognition cannot become a new turn after interruption. TTS requests are bounded and audio responses are not cached.

## Installation and startup

Run `powershell -ExecutionPolicy Bypass -File scripts/setup-voice.ps1` from the repository. It installs pinned primary dependencies and downloads model files into `data/models`. The manifest records the downloaded model revisions. Installation needs internet; the running service sets Hugging Face and Transformers offline mode and supplies local paths to every model.

Configure `.env`:

```dotenv
TTS_PROVIDER=omnivoice
TTS_MODEL_PATH=C:\path\to\darius\data\models\omnivoice
TTS_SERVICE_URL=http://127.0.0.1:8002
TRANSCRIPTION_PROVIDER=r2t2
R2T2_WS_URL=ws://127.0.0.1:8272/asr_stream_api_v1
R2T2_LANGUAGE=English
```

R2T2 is installed under `vendor/Confucius4-R2T2` and runs in the localhost-only
Docker container `darius-r2t2` on port `8272`. The container uses the local
`checkpoints/Confucius4-R2T2` and `checkpoints/vad/Stream-VAD` files, exposes
80% of the GPU, and caps vLLM's context at 32k tokens so it can coexist with
ComfyUI. The first launch loads the 4 GB checkpoint and compiles CUDA kernels;
keep the container running between sessions to avoid repeating that warmup.

The regular `start-darius.bat` launcher starts the installed service in a hidden process. To start only voice:

```powershell
.venv-voice/Scripts/python.exe -m uvicorn apps.voice.server:app --host 127.0.0.1 --port 8002 --ws-max-size 32768 --ws-max-queue 4
```

`GET /health` reports model-file readiness, whether TTS has loaded, the device, and the last synthesis error. The main API's TTS health checks this service instead of declaring success solely because a model path exists. The existing `LocalTtsProvider` adapter can write the generated WAV to a production destination.

CPU is the configured default: the RTX 5080 had only about 2 GB free during setup. OmniVoice warms in a background thread at service startup. The first measured cold synthesis took 92 seconds; a subsequent short reply took 4.13 seconds on CPU. Those are synthetic samples, not guarantees for long replies. The model remains in RAM across turns. A CUDA environment and `DARIUS_VOICE_DEVICE=cuda:0` can be configured separately if GPU memory is available; CUDA was not installed or validated for this speech environment.

## Model licensing

The [OmniVoice code](https://github.com/k2-fsa/OmniVoice) is Apache-2.0, but the downloaded [pretrained model card](https://huggingface.co/k2-fsa/OmniVoice#license) states CC-BY-NC/non-commercial due to training-data restrictions. Its bundled audio-tokenizer card does not provide a complete license declaration. This remains the replaceable prototype adapter required by the handoff, not a commercial-use clearance. Commercial production needs appropriate weight licensing or another provider.

The [Vosk model catalog](https://alphacephei.com/vosk/models) lists the selected small English model as Apache-2.0. [Faster-whisper](https://github.com/SYSTRAN/faster-whisper) supplies the local command-transcription runtime.

## Validation

### Earlier conversational replies

During local playback, say **“Darius, stop”** (or “Darius, wait”) or use
**Interrupt & speak**. This stops speech and its prefetched chunk without ending
the microphone session. The current model/tool task continues in chat; interruption
does not cancel a render. If that task is still busy, one transcribed follow-up is
shown as a held draft and sent when it finishes. End voice discards that draft.

Playback audio now prefetches at most one next chunk on the existing CPU engine.
Ordinary speech is not sent as a chat turn during playback: a constrained Vosk
recognizer and the general recognizer must agree on an addressed stop phrase with
high confidence. Browser echo cancellation remains enabled. Headphones are best
for reliable hands-free interruption; speaker acoustics can still affect detection,
and the button remains available. This is explicit-command interruption, not
unrestricted full-duplex conversation.

Regular chat uses the streaming reply endpoint. A conservative allowlist sends greetings,
general explanations, and text-only brainstorming through a smaller, single-turn context
without the workflow catalog or tool planner. Attachments, workflow selections, ambiguous
follow-ups, and saved agent tasks retain the verified tool path. Provider selection and
rendering permissions are unchanged.

OpenAI, DeepSeek, Ollama, and llama.cpp transport text deltas to chat; local speech begins
with complete sentences rather than waiting for the entire answer. Speech chunks stay on
the configured CPU engine, are limited to the existing 600-character spoken budget, and
keep microphone capture paused until both the reply and playback finish. Stopping or
muting cancels queued speech. OpenCode CLI and tool-driven replies currently speak after
their completed, validated answer; they do not expose unverified tool prose as early audio.

Incomplete streams show a retryable error and never save a partial answer as a completed
assistant message. The existing reply endpoint remains compatible with older clients.

Synthetic Windows speech samples exercised the actual local Vosk/Whisper WebSocket path: three wake phrases activated, four unrelated phrases did not, and an inline forest request reached transcription. Real OmniVoice synthesis and the application's `LocalTtsProvider` both produced WAV files. Test audio is under ignored `data/`; no user microphone audio was recorded during development, and no real assistant or generation request was submitted for these checks.
