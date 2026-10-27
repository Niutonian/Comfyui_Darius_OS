# Pipecat voice

Pipecat is an optional, separately installed CPU speech sidecar on port **8003**.

For microphone access from phones/tablets/other LAN computers, see [Secure LAN microphones](lan-https.md). HTTPS uses the same-origin `/voice/pipecat` gateway rather than exposing an insecure voice connection to the browser. The existing localhost path remains unchanged.
The fullscreen and normal chat use it through the same project conversation and
assistant callback. It does not replace the Darius planner, selected model,
workflow executor, asset checks, job deduplication, or approval rules.

## Use

After refreshing the app, choose **Pipecat · CPU streaming** in fullscreen voice
settings or **Settings → Local conversation engine**. Start the microphone once;
it remains active during reply generation and audio playback. Speak to interrupt
the voice. Existing model/tool requests keep completing safely in chat; a held
follow-up waits for that request before it is submitted. Interrupting speech is
not permission to cancel or duplicate a render.

Choose a Kokoro voice under **Pipecat voice** in Settings. Spoken-reply mute and
the pause limit still apply. Smart Turn can finish a turn before that silence
limit when it detects a complete utterance. Both speech recognition and voices
are configured for English in this first integration.

**Check Pipecat**, **Check service**, and **Test speaker** use the selected engine.
Service status includes the latest transcription and speech first-audio timing
without storing microphone recordings or transcripts in diagnostics.

**Classic local voice** remains selectable, including device/OmniVoice choices
and the original wake-word path. Pipecat currently starts by microphone button,
not by wake word. Existing cloud voice remains separate and billed as before.

## Installation / startup

```powershell
./scripts/setup-pipecat.ps1
```

The setup uses `.venv-pipecat` and pinned requirements in
`apps/voice/requirements-pipecat.txt`. It downloads Kokoro release assets to
`data/models/pipecat`; release digests are verified when published, and local
SHA-256/size records are saved. It does not install Torch/CUDA or modify the API
or Classic voice virtual environments. Existing local Vosk and Whisper assets
from voice setup are prerequisites (`data/models/vosk-model-small-en-us-0.15`
and `data/models/whisper-base-en`). Smart Turn and Silero weights ship with Pipecat.

The normal Darius launcher starts the sidecar if the environment and model
manifest exist. For a manual start:

```powershell
.venv-pipecat/Scripts/python.exe -m uvicorn apps.voice.pipecat_server:app --host 0.0.0.0 --port 8003 --ws-max-size 32768 --ws-max-queue 16
```

Health is available at `http://127.0.0.1:8003/health`; it reports warming/failure
until CPU model initialization and decoder warmup complete. Startup logs are
written under `data/pipecat-*.log` / `data/pipecat-start-*.log` by the launcher.
The sidecar does not need API keys, an external voice account, or a LiveKit/Daily
server. Browser microphone security requirements still apply; LAN HTTP does not
automatically grant microphone permission.

## Audio / execution boundary

1. The browser sends 16 kHz mono PCM over an origin-checked WebSocket, with
   64 ms capture packets rather than the Classic 250 ms packet size.
2. Pipecat Silero VAD and CPU Smart Turn endpoint the audio. Vosk supplies draft
   captions; local int8 Faster-Whisper finalizes the complete turn.
3. The final transcript and unique turn ID go back to the browser. The existing
   Darius chat API handles saving, provider selection, tools, and verified results.
4. Only the current turn's reply text enters the Pipecat `PipelineWorker`.
   Custom frame processors adapt shared CPU Kokoro inference to Pipecat audio
   frames. Audio streams back in 100 ms PCM packets, with gapless scheduling in
   Web Audio instead of downloading whole WAV files per sentence.
5. Pipecat interruption frames cancel speech processing; turn IDs discard late
   audio/replies. The browser never aborts the underlying workflow request.

Capture continues while final transcription runs; bounded audio buffering keeps
the next utterance's first words. Memory, text, packet sizes, and concurrent
sessions are bounded. Up to two voice sessions share the CPU model resources.
Empty speech and direct reply echoes are filtered conservatively. Acoustic echo
cancellation still depends on the browser/device; headphones may be needed in
noisy or speaker-heavy setups. This is a streaming cascaded pipeline, not a claim
of native speech-to-speech parity on every device.

The current transport is a local WebSocket adapter, not Pipecat SmallWebRTC. This
keeps the existing browser capture and Darius execution boundary intact; no
second agent is granted unrestricted MCP access. Speech is capped to 600 reply
characters in the browser, preserving the existing spoken-reply budget.

## Verification

```powershell
.venv-pipecat/Scripts/python.exe -m pytest tests/test_pipecat_voice.py
.venv-pipecat/Scripts/python.exe scripts/check-pipecat.py
```

The smoke test synthesizes a fixed local utterance, sends it through the real
speech session, and streams a fixed response. It does not open a microphone,
call a Darius model, or submit a render. Results go to `data/pipecat-smoke.json`.
These timings exclude LLM/workflow time and should not be read as end-to-end
human conversation latency.

Frontend tests cover streamed playback, uninterrupted capture, stale-turn
rejection, deferred follow-ups, disconnection, and keeping Classic behavior.
The fullscreen fixture audit supports both local engines.

Primary references: [Pipecat](https://github.com/pipecat-ai/pipecat),
[Smart Turn](https://github.com/pipecat-ai/smart-turn),
[Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx).
