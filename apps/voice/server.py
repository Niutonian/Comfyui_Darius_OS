"""Loopback-only speech service. Audio is transient and never sent to a cloud."""
from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import re
import socket
import threading
import subprocess
from typing import Literal
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "data" / "models"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HOME"] = str(MODELS / "hf-cache")
from apps.voice.origins import voice_origins
ORIGINS = voice_origins(ROOT)


@asynccontextmanager
async def lifespan(_app):
    # Keep HTTP/wake detection available while the larger TTS model warms up.
    threading.Thread(target=warmup, daemon=True, name="omnivoice-warmup").start()
    yield


app = FastAPI(title="Darius local voice", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=sorted(ORIGINS), allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
tts_lock = threading.Lock()
recognition_lock = threading.Lock()
transcription_lock = threading.Lock()
tts_model = None
recognition_model = None
transcription_model = None
transcription_error = ""
transcription_override: str | None = None
tts_error = ""
WAKE = re.compile(r"^(?:(?:hello|hey|hi|okay|ok)\s+)?darius\b[\s,.!?]*", re.I)


def wake_command(text: str) -> str | None:
    match = WAKE.match(text.strip())
    return text.strip()[match.end():].strip() if match else None


def detected_command(wake: dict, full: dict) -> str | None:
    if wake_command(wake.get("text", "")) is None:
        return None
    direct = wake_command(full.get("text", ""))
    if direct is not None:
        return direct
    names = [word for word in wake.get("result", []) if word["word"] == "darius" and word.get("conf", 0) >= 0.8]
    if not names:
        return None
    # The general recognizer may spell the name differently. Word timing keeps
    # an inline command while excluding those misheard name syllables.
    end = names[0]["end"]
    return " ".join(word["word"] for word in full.get("result", []) if word["start"] >= end - 0.03 and word["end"] > end + 0.05)


def get_recognition_model():
    global recognition_model
    with recognition_lock:
        if recognition_model is None:
            from vosk import Model, SetLogLevel
            SetLogLevel(-1)
            recognition_model = Model(str(MODELS / "vosk-model-small-en-us-0.15"))
    return recognition_model


def r2t2_reachable() -> bool:
    uri = os.getenv("R2T2_WS_URL", "ws://127.0.0.1:8272/asr_stream_api_v1").strip()
    parsed = urlparse(uri)
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
        return False
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=0.3):
            return True
    except OSError:
        return False


def transcription_provider() -> str:
    if transcription_override in {"r2t2", "faster-whisper"}:
        return transcription_override
    provider = os.getenv("TRANSCRIPTION_PROVIDER", "faster-whisper").strip().lower() or "faster-whisper"
    return "faster-whisper" if provider in {"whisper", "faster-whisper"} else provider


def r2t2_session_header() -> dict:
    return {
        "channels": 1,
        "sample_rate": 16000,
        "requestId": uuid.uuid4().hex,
        "language": os.getenv("R2T2_LANGUAGE", "English").strip() or "English",
        "use_vad": False,
        "secret_key": os.getenv("R2T2_SECRET_KEY", "test0102").strip() or "test0102",
        "mode": "slow",
    }


def assemble_r2t2_transcript(messages: list[dict]) -> str:
    """Join R2T2 text deltas. The service sends new characters, not the full line."""
    parts: list[str] = []
    finished = False
    for payload in messages:
        status = payload.get("status")
        if status == "connected":
            continue
        if status not in {None, "success"}:
            raise RuntimeError(str(payload.get("msg") or payload.get("message") or payload)[:500])
        message = payload.get("msg") or {}
        if not isinstance(message, dict):
            continue
        text = message.get("text") or ""
        if text:
            parts.append(text)
        if message.get("reset"):
            finished = True
            break
    if not finished:
        raise RuntimeError("R2T2 closed before a final transcript")
    transcript = "".join(parts).strip()
    if not transcript:
        raise RuntimeError("R2T2 returned an empty transcript")
    return transcript


def transcribe_with_r2t2(pcm: bytes) -> str:
    """Send one completed Vosk turn through the local R2T2 WebSocket server."""
    from websockets.sync.client import connect
    from websockets.exceptions import ConnectionClosed

    uri = os.getenv("R2T2_WS_URL", "ws://127.0.0.1:8272/asr_stream_api_v1").strip()
    parsed = urlparse(uri)
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
        raise RuntimeError("R2T2_WS_URL must be a ws:// or wss:// URL")
    received: list[dict] = []
    frame_bytes = int(16000 * 2 * 0.16)
    with connect(uri, open_timeout=8, close_timeout=2, max_size=1_048_576) as socket:
        socket.send(json.dumps(r2t2_session_header()))
        for offset in range(0, len(pcm), frame_bytes):
            socket.send(pcm[offset:offset + frame_bytes])
        socket.send("YOUDAO_ONETIME_ASR_STREAM_EOS")
        while True:
            try:
                message = socket.recv(timeout=25)
            except ConnectionClosed as exc:
                raise RuntimeError(f"R2T2 closed the transcription session ({exc})") from exc
            except TimeoutError:
                raise RuntimeError("R2T2 did not return a final transcript") from None
            if isinstance(message, bytes):
                continue
            received.append(json.loads(message))
            if (received[-1].get("msg") or {}).get("reset") if isinstance(received[-1].get("msg"), dict) else False:
                break
    return assemble_r2t2_transcript(received)


def transcribe_with_faster_whisper(pcm: bytes) -> str:
    global transcription_model
    import numpy as np
    from faster_whisper import WhisperModel
    with transcription_lock:
        if transcription_model is None:
            transcription_model = WhisperModel(str(MODELS / "whisper-base-en"), device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True)
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        segments, _ = transcription_model.transcribe(audio, language="en", beam_size=5, condition_on_previous_text=False, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()


def detected_interruption(constrained, general):
    """Require both recognizers to agree on an addressed stop command."""
    def normalized(result):
        text = " ".join(str(result.get("text", "")).lower().split())
        # The bundled general English model spells this name "darrius".
        return re.sub(r"\bdarrius\b", "darius", text)
    phrase = normalized(general)
    return (
        phrase in {"darius stop", "hey darius stop", "darius wait"}
        and normalized(constrained) == phrase
        and bool(constrained.get("result"))
        and all(word.get("conf", 0) >= 0.75 for word in constrained["result"])
    )


def trailing_silence(pcm: bytes, seconds: float = 0.85, threshold: int = 450) -> bool:
    """True when a spoken turn has already started and then gone quiet."""
    need = int(16000 * 2 * seconds)
    if len(pcm) < need + 16000:
        return False
    samples = memoryview(pcm[-need:]).cast("h")
    return sum(abs(sample) for sample in samples) / len(samples) < threshold


def transcribe(pcm: bytes) -> str:
    global transcription_error
    provider = transcription_provider()
    if provider == "r2t2":
        if not r2t2_reachable():
            transcription_error = "R2T2 is unavailable; using CPU Faster-Whisper."
            return transcribe_with_faster_whisper(pcm)
        try:
            result = transcribe_with_r2t2(pcm)
            transcription_error = ""
            return result
        except Exception as exc:
            transcription_error = f"R2T2 unavailable; faster-whisper fallback used: {exc}"
            return transcribe_with_faster_whisper(pcm)
    if provider not in {"faster-whisper", "whisper"}:
        transcription_error = f"Unknown TRANSCRIPTION_PROVIDER {provider!r}; using faster-whisper"
    else:
        transcription_error = ""
    return transcribe_with_faster_whisper(pcm)


def load_tts_model():
    global tts_model
    if tts_model is None:
        import torch
        from omnivoice import OmniVoice
        torch.set_num_threads(8)
        device = os.getenv("DARIUS_VOICE_DEVICE", "cpu")
        tts_model = OmniVoice.from_pretrained(str(MODELS / "omnivoice"), device_map=device,
                                            dtype=torch.float32 if device == "cpu" else torch.float16)
    return tts_model


def warmup():
    global tts_error
    try:
        with tts_lock:
            load_tts_model()
    except Exception as exc:
        tts_error = str(exc)


SUPPORTED_VOICE_STYLES = frozenset({
    "", "male", "female", "male, low pitch", "female, low pitch",
    "male, british accent", "female, british accent",
    "male, american accent", "female, american accent",
    "male, australian accent", "female, australian accent",
    "male, indian accent", "female, indian accent", "whisper",
})


def resolve_voice_style(description: str) -> str | None:
    style = description.strip().lower()
    return style if style in SUPPORTED_VOICE_STYLES and style else None


def synthesize(text: str, voice_description: str = "") -> bytes:
    global tts_model, tts_error
    if not tts_lock.acquire(timeout=120):
        raise HTTPException(409, "OmniVoice is speaking another request. Please try again shortly.")
    try:
        import soundfile as sf
        # Browser preferences from older versions may contain unsupported prose.
        # A valid reply must still be spoken with the default voice.
        audio = load_tts_model().generate(text=text, language="English", num_step=16,
                                          instruct=resolve_voice_style(voice_description))
        output = io.BytesIO()
        sf.write(output, audio[0], 24000, format="WAV", subtype="PCM_16")
        tts_error = ""
        return output.getvalue()
    except HTTPException:
        raise
    except Exception as exc:
        tts_error = str(exc)
        raise HTTPException(503, f"Local OmniVoice could not synthesize speech: {exc}") from exc
    finally:
        tts_lock.release()


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice_description: str = Field(default="", max_length=300)
    engine: Literal["system", "omnivoice"] = "omnivoice"
    voice: str = Field(default="", max_length=300)


def system_speech(payload: dict) -> bytes:
    if os.name != "nt":
        raise HTTPException(503, "Windows speech is unavailable on this server.")
    executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "apps/voice/system-speech.ps1")],
            input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(503, "Windows speech did not respond. Choose OmniVoice or retry the speaker test.") from exc
    if result.returncode:
        raise HTTPException(503, "Windows speech is unavailable. Install an English Windows voice or choose OmniVoice.")
    return result.stdout


@app.get("/voices")
def system_voices():
    return {"voices": json.loads(system_speech({"action": "voices"}).decode("utf-8-sig"))}


class TranscriptionChoice(BaseModel):
    provider: str = Field(pattern=r"^(r2t2|faster-whisper)$")


@app.get("/health")
def health():
    provider = transcription_provider()
    whisper_ready = (MODELS / "whisper-base-en" / "model.bin").is_file()
    r2t2_ready = r2t2_reachable()
    active_provider = "r2t2" if provider == "r2t2" and r2t2_ready else "faster-whisper"
    return {"service": "darius-local-voice", "local_only": True,
            "wake_ready": (MODELS / "vosk-model-small-en-us-0.15" / "am" / "final.mdl").is_file(),
            "transcription_ready": whisper_ready or (provider == "r2t2" and r2t2_ready),
            "transcription_provider": provider,
            "transcription_active_provider": active_provider,
            "transcription_providers": {"r2t2": r2t2_ready, "faster-whisper": whisper_ready},
            "r2t2_ws_url": os.getenv("R2T2_WS_URL", "ws://127.0.0.1:8272/asr_stream_api_v1") if provider == "r2t2" else None,
            "transcription_error": ("R2T2 is offline. Using CPU Faster-Whisper." if provider == "r2t2" and not r2t2_ready and whisper_ready else transcription_error),
            "tts_ready": (MODELS / "voice-manifest.json").is_file() and (MODELS / "omnivoice" / "model.safetensors").is_file(),
            "tts_loaded": tts_model is not None, "tts_provider": "omnivoice",
            "device": os.getenv("DARIUS_VOICE_DEVICE", "cpu"), "error": tts_error}


@app.post("/transcription")
def choose_transcription(body: TranscriptionChoice, request: Request):
    global transcription_override
    if request.headers.get("origin") and request.headers["origin"] not in ORIGINS:
        raise HTTPException(403, "This origin cannot change local transcription.")
    transcription_override = body.provider
    return health()


@app.post("/tts")
def tts(body: SpeechRequest, request: Request):
    if request.headers.get("origin") and request.headers["origin"] not in ORIGINS:
        raise HTTPException(403, "This origin cannot use local speech.")
    if not body.text.strip():
        raise HTTPException(422, "Speech text is empty.")
    if body.engine == "system":
        audio = system_speech({"action": "speak", "text": body.text, "voice": body.voice})
        if not audio.startswith(b"RIFF") or len(audio) <= 44:
            raise HTTPException(503, "Windows speech returned no playable audio.")
    else:
        audio = synthesize(body.text, body.voice_description) if body.voice_description else synthesize(body.text)
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.websocket("/listen")
async def listen(socket: WebSocket):
    if socket.headers.get("origin") not in ORIGINS:
        await socket.close(code=1008)
        return
    await socket.accept()
    try:
        from vosk import KaldiRecognizer
        model = await asyncio.to_thread(get_recognition_model)
        recognizer = KaldiRecognizer(model, 16000)
        recognizer.SetWords(True)
        wake_recognizer = KaldiRecognizer(model, 16000, json.dumps(["darius", "hello darius", "hey darius", "hi darius", "okay darius", "[unk]"]))
        wake_recognizer.SetWords(True)
        interrupt_recognizer = None
        mode = "wake"
        epoch = 0
        silence_seconds = 1.2
        speech_started = False
        draft_segments = []
        last_draft = ""
        utterance = bytearray()
        await socket.send_json({"type": "ready"})
        while True:
            message = await socket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("text") is not None:
                command = json.loads(message["text"])
                if command.get("mode") not in {"wake", "conversation", "paused", "interrupt"}:
                    await socket.close(code=1008)
                    break
                mode = command["mode"]
                if mode == "interrupt" and interrupt_recognizer is None:
                    interrupt_recognizer = KaldiRecognizer(model, 16000, json.dumps(["darius stop", "hey darius stop", "darius wait", "[unk]"]))
                    interrupt_recognizer.SetWords(True)
                epoch = command.get("epoch", 0)
                silence_seconds = max(0.5, min(3.0, float(command.get("silence_seconds", 1.2))))
                speech_started = False
                draft_segments.clear()
                last_draft = ""
                recognizer.Reset()
                wake_recognizer.Reset()
                if interrupt_recognizer:
                    interrupt_recognizer.Reset()
                utterance.clear()
                continue
            pcm = message.get("bytes", b"")
            if len(pcm) > 32000 or len(pcm) % 2:
                await socket.close(code=1009)
                break
            if mode == "paused" or not pcm:
                continue
            if mode == "interrupt":
                # During playback only an explicit addressed stop is accepted.
                # No partial chat transcription, Whisper request, or reply echo.
                general_final = await asyncio.to_thread(recognizer.AcceptWaveform, pcm)
                stop_final = await asyncio.to_thread(interrupt_recognizer.AcceptWaveform, pcm)
                if stop_final or general_final:
                    constrained = json.loads(interrupt_recognizer.Result() if stop_final else interrupt_recognizer.FinalResult())
                    general = json.loads(recognizer.Result() if general_final else recognizer.FinalResult())
                    recognizer.Reset()
                    interrupt_recognizer.Reset()
                    if detected_interruption(constrained, general):
                        mode = "paused"
                        await socket.send_json({"type": "interrupt", "epoch": epoch})
                continue
            if mode == "conversation":
                samples = memoryview(pcm).cast("h")
                speech_started = speech_started or sum(abs(sample) for sample in samples) / len(samples) >= 450
                if not speech_started:
                    # Keep a short pre-roll without sending idle silence to Whisper.
                    utterance.extend(pcm)
                    del utterance[:-8000]
                    continue
            utterance.extend(pcm)
            if len(utterance) > 16000 * 2 * 30:
                if mode == "conversation":
                    # Finalize a long turn instead of disconnecting the microphone.
                    pass
                else:
                    utterance.clear()
                    recognizer.Reset()
                    wake_recognizer.Reset()
                    continue
            if mode == "wake":
                await asyncio.to_thread(recognizer.AcceptWaveform, pcm)
                final = await asyncio.to_thread(wake_recognizer.AcceptWaveform, pcm)
                if final:
                    wake_result = json.loads(wake_recognizer.Result())
                    command = detected_command(wake_result, json.loads(recognizer.FinalResult()))
                    if command:
                        names = [word for word in wake_result.get("result", []) if word["word"] == "darius"]
                        if names:
                            offset = int(names[0]["end"] * 16000) * 2
                            command = await asyncio.to_thread(transcribe, bytes(utterance[offset:]))
                    utterance.clear()
                    recognizer.Reset()
                    wake_recognizer.Reset()
                    if command is not None:
                        mode = "paused" if command else "conversation"
                        await socket.send_json({"type": "wake", "text": command, "epoch": epoch})
                continue
            final = await asyncio.to_thread(recognizer.AcceptWaveform, pcm)
            if final:
                # Result() must be consumed. Leaving it pending makes every later
                # frame look like the end of an utterance, so the next thing said is lost.
                segment = json.loads(await asyncio.to_thread(recognizer.Result)).get("text", "").strip()
                if segment:
                    draft_segments.append(segment)
            partial = "" if final else json.loads(recognizer.PartialResult()).get("partial", "").strip()
            draft = " ".join([*draft_segments, partial]).strip()
            if draft != last_draft:
                await socket.send_json({"type": "partial", "text": draft, "epoch": epoch})
                last_draft = draft
            quiet = trailing_silence(utterance, seconds=silence_seconds)
            if quiet or len(utterance) >= 16000 * 2 * 30:
                audio = bytes(utterance)
                utterance.clear()
                recognizer.Reset()
                speech_started = False
                mode = "paused"
                draft_segments.clear()
                last_draft = ""
                await socket.send_json({"type": "hold", "epoch": epoch})
                try:
                    text = await asyncio.to_thread(transcribe, audio) if audio else ""
                except Exception as exc:
                    mode = "conversation"
                    await socket.send_json({"type": "listen", "epoch": epoch})
                    await socket.send_json({"type": "error", "message": f"Transcription failed: {exc}"[:500]})
                    continue
                if text:
                    await socket.send_json({"type": "final", "text": text, "epoch": epoch})
                else:
                    mode = "conversation"
                    await socket.send_json({"type": "listen", "epoch": epoch})
                continue
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await socket.send_json({"type": "error", "message": "Local recognition failed. Check the voice service and model files."})
            await socket.close(code=1011)
        except RuntimeError:
            pass
