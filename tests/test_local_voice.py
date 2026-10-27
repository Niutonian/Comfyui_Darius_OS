import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

spec = importlib.util.spec_from_file_location("voice_server", Path(__file__).parents[1] / "apps/voice/server.py")
voice = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = voice
spec.loader.exec_module(voice)


@pytest.mark.parametrize("text,command", [
    ("Darius", ""), ("hello darius", ""), ("Hey Darius make a video", "make a video"),
    ("darius make a forest", "make a forest"), ("we spoke about darius", None),
    ("various pictures", None), ("hello everyone", None), ("dariuses", None),
])
def test_wake_requires_addressing_darius(text, command):
    assert voice.wake_command(text) == command


def test_listening_filters_ambient_audio_and_pauses_after_command(monkeypatch):
    class Recognizer:
        def __init__(self, *_):
            self.text = ""
        def AcceptWaveform(self, data):
            self.text = data.decode().strip()
            return True
        def Result(self):
            import json
            return json.dumps({"text": self.text})
        def Reset(self):
            pass
        def SetWords(self, _):
            pass
        def FinalResult(self):
            return self.Result()
    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(KaldiRecognizer=Recognizer))
    monkeypatch.setattr(voice, "get_recognition_model", lambda: object())
    monkeypatch.setattr(voice, "transcribe", lambda pcm: pcm.decode().strip())
    monkeypatch.setattr(voice, "trailing_silence", lambda *args, **kwargs: True)
    with TestClient(voice.app).websocket_connect("/listen", headers={"origin": "http://127.0.0.1:3000"}) as ws:
        assert ws.receive_json() == {"type": "ready"}
        for text in ["ordinary conversation", "hello darius create a video"]:
            ws.send_bytes(text.ljust(len(text) + len(text) % 2).encode())
        # Ambient speech must not appear in the browser, even as a partial result.
        assert ws.receive_json() == {"type": "wake", "text": "create a video", "epoch": 0}
        ws.send_bytes(b"ignored while speaking  ")
        ws.send_json({"mode": "conversation"})
        ws.send_bytes(b"another command ")
        assert ws.receive_json() == {"type": "partial", "text": "another command", "epoch": 0}
        assert ws.receive_json()["type"] == "hold"
        assert ws.receive_json() == {"type": "final", "text": "another command", "epoch": 0}


def test_live_draft_preserves_segments_and_resets_between_turns(monkeypatch):
    import json
    class Recognizer:
        def __init__(self, *_): self.frame = 0
        def SetWords(self, *_): pass
        def Reset(self): self.frame = 0
        def AcceptWaveform(self, _):
            self.frame += 1
            return self.frame == 2
        def Result(self): return json.dumps({"text": "make a forest"})
        def PartialResult(self):
            return json.dumps({"partial": {1: "make a", 3: "at night", 4: "at night"}.get(self.frame, "")})
    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(KaldiRecognizer=Recognizer))
    monkeypatch.setattr(voice, "get_recognition_model", lambda: object())
    monkeypatch.setattr(voice, "trailing_silence", lambda audio, **_: len(audio) >= 8)
    calls = []
    monkeypatch.setattr(voice, "transcribe", lambda audio: calls.append(audio) or "Make a forest at night.")
    with TestClient(voice.app).websocket_connect("/listen", headers={"origin": "http://127.0.0.1:3000"}) as ws:
        assert ws.receive_json()["type"] == "ready"
        for epoch in (1, 2):
            ws.send_json({"mode": "conversation", "epoch": epoch})
            for expected in ("make a", "make a forest", "make a forest at night"):
                ws.send_bytes(b"\xff\x7f")
                assert ws.receive_json() == {"type": "partial", "text": expected, "epoch": epoch}
            ws.send_bytes(b"\xff\x7f")
            assert ws.receive_json()["type"] == "hold"  # No duplicate draft.
            assert ws.receive_json() == {"type": "final", "text": "Make a forest at night.", "epoch": epoch}
        assert len(calls) == 2


def test_untrusted_origin_cannot_open_microphone_session():
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with TestClient(voice.app).websocket_connect("/listen", headers={"origin": "https://example.com"}):
            pass


def test_idle_silence_never_reaches_whisper(monkeypatch):
    class Recognizer:
        def __init__(self, *_): pass
        def SetWords(self, *_): pass
        def Reset(self): pass
        def AcceptWaveform(self, _): raise AssertionError("Idle audio reached recognition")
    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(KaldiRecognizer=Recognizer))
    monkeypatch.setattr(voice, "get_recognition_model", lambda: object())
    monkeypatch.setattr(voice, "transcribe", lambda _: pytest.fail("Silence reached Whisper"))
    with TestClient(voice.app).websocket_connect("/listen", headers={"origin": "http://127.0.0.1:3000"}) as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"mode": "conversation", "silence_seconds": 1.2})
        for _ in range(8):
            ws.send_bytes(bytes(8000))


def test_inline_command_survives_misheard_name_without_sending_name_syllables():
    wake = {"text": "hello darius [unk]", "result": [{"word": "darius", "end": 1.0, "conf": 1.0}]}
    full = {"text": "hello does he use make a forest", "result": [
        {"word": "use", "start": 0.8, "end": 1.0}, {"word": "make", "start": 1.02, "end": 1.3},
        {"word": "a", "start": 1.3, "end": 1.4}, {"word": "forest", "start": 1.4, "end": 1.8},
    ]}
    assert voice.detected_command(wake, full) == "make a forest"


def test_r2t2_session_sends_the_required_header_and_joins_deltas(monkeypatch):
    import json
    sent = []
    replies = [
        json.dumps({"status": "connected", "msg": ""}),
        json.dumps({"status": "success", "msg": {"text": "hel", "reset": False}}),
        json.dumps({"status": "success", "msg": {"text": "lo there", "reset": True}}),
    ]

    class Socket:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def send(self, data):
            sent.append(data)
        def recv(self, timeout=None):
            return replies.pop(0)

    monkeypatch.setattr("websockets.sync.client.connect", lambda *args, **kwargs: Socket())
    assert voice.transcribe_with_r2t2(b"\x00\x01" * 1600) == "hello there"
    header = json.loads(sent[0])
    assert header["requestId"]
    assert header["sample_rate"] == 16000
    assert header["secret_key"]
    assert sent[-1] == "YOUDAO_ONETIME_ASR_STREAM_EOS"


def test_empty_r2t2_result_falls_back_to_whisper(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "r2t2")
    monkeypatch.setattr(voice, "r2t2_reachable", lambda: True)
    voice.transcription_override = None
    monkeypatch.setattr(voice, "transcribe_with_r2t2", lambda _pcm: (_ for _ in ()).throw(RuntimeError("R2T2 returned an empty transcript")))
    monkeypatch.setattr(voice, "transcribe_with_faster_whisper", lambda _pcm: "whisper heard it")
    assert voice.transcribe(b"audio") == "whisper heard it"
    assert "faster-whisper fallback" in voice.transcription_error


def test_transcription_choice_overrides_the_environment(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "r2t2")
    voice.transcription_override = None
    assert voice.transcription_provider() == "r2t2"
    client = TestClient(voice.app)
    saved = client.post("/transcription", json={"provider": "faster-whisper"}, headers={"origin": "http://127.0.0.1:3000"})
    assert saved.status_code == 200
    assert saved.json()["transcription_provider"] == "faster-whisper"
    assert voice.transcription_provider() == "faster-whisper"
    voice.transcription_override = None


def test_r2t2_is_used_for_active_transcription_with_fallback(monkeypatch):
    calls = []
    voice.transcription_override = None
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "r2t2")
    monkeypatch.setattr(voice, "r2t2_reachable", lambda: True)
    monkeypatch.setattr(voice, "transcribe_with_r2t2", lambda pcm: calls.append(("r2t2", pcm)) or "r2t2 text")
    monkeypatch.setattr(voice, "transcribe_with_faster_whisper", lambda pcm: calls.append(("whisper", pcm)) or "whisper text")
    assert voice.transcribe(b"audio") == "r2t2 text"
    assert calls == [("r2t2", b"audio")]

    def unavailable(_pcm):
        raise RuntimeError("service offline")
    monkeypatch.setattr(voice, "transcribe_with_r2t2", unavailable)
    assert voice.transcribe(b"audio") == "whisper text"
    assert calls[-1] == ("whisper", b"audio")
    assert "fallback" in voice.transcription_error


def test_offline_r2t2_uses_ready_cpu_whisper_without_blocking_voice(tmp_path, monkeypatch):
    model = tmp_path / "whisper-base-en" / "model.bin"
    model.parent.mkdir()
    model.touch()
    monkeypatch.setattr(voice, "MODELS", tmp_path)
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "r2t2")
    monkeypatch.setattr(voice, "transcription_override", None)
    monkeypatch.setattr(voice, "r2t2_reachable", lambda: False)
    monkeypatch.setattr(voice, "transcribe_with_r2t2", lambda _: pytest.fail("Offline R2T2 was called"))
    monkeypatch.setattr(voice, "transcribe_with_faster_whisper", lambda _: "hello")
    status = voice.health()
    assert status["transcription_ready"] is True
    assert status["transcription_provider"] == "r2t2"
    assert status["transcription_active_provider"] == "faster-whisper"
    assert voice.transcribe(b"audio") == "hello"


def test_tts_validation_and_no_cache(monkeypatch):
    monkeypatch.setattr(voice, "synthesize", lambda text: b"RIFF0000WAVE" + text.encode())
    client = TestClient(voice.app)
    assert client.post("/tts", json={"text": "hello"}, headers={"origin": "https://example.com"}).status_code == 403
    assert client.post("/tts", json={"text": " "}).status_code == 422
    assert client.post("/tts", json={"text": "x" * 4001}).status_code == 422
    reply = client.post("/tts", json={"text": "hello"})
    assert reply.status_code == 200
    assert reply.headers["content-type"] == "audio/wav"
    assert reply.headers["cache-control"] == "no-store"


def test_tts_passes_bounded_voice_description(monkeypatch):
    calls = []
    monkeypatch.setattr(voice, "synthesize", lambda text, style: calls.append((text, style)) or b"RIFF0000WAVE")
    client = TestClient(voice.app)
    assert client.post("/tts", json={"text": "Hello", "voice_description": "Warm low voice"}).status_code == 200
    assert calls == [("Hello", "Warm low voice")]
    assert client.post("/tts", json={"text": "Hello", "voice_description": "x" * 301}).status_code == 422


def test_unsupported_saved_voice_uses_default_instead_of_silencing_reply():
    assert voice.resolve_voice_style("nigerian") is None
    assert voice.resolve_voice_style("Warm, calm, low-pitched voice") is None
    assert voice.resolve_voice_style("female, british accent") == "female, british accent"


def test_windows_voice_route_validates_audio_and_does_not_load_omnivoice(monkeypatch):
    calls = []
    def system(payload):
        calls.append(payload)
        return b"RIFF" + b"0" * 80
    monkeypatch.setattr(voice, "system_speech", system)
    monkeypatch.setattr(voice, "synthesize", lambda *_: pytest.fail("Fast voice loaded OmniVoice"))
    client = TestClient(voice.app)
    for text in ["First turn", "Second turn", "Third turn"]:
        response = client.post("/tts", json={"text": text, "engine": "system", "voice": "Microsoft Zira Desktop"})
        assert response.status_code == 200
        assert response.content.startswith(b"RIFF")
        assert response.headers["cache-control"] == "no-store"
    assert len(calls) == 3
    assert calls[-1]["voice"] == "Microsoft Zira Desktop"
    monkeypatch.setattr(voice, "system_speech", lambda _: b"")
    assert client.post("/tts", json={"text": "Test", "engine": "system"}).status_code == 503
    assert client.post("/tts", json={"text": "Test", "engine": "unknown"}).status_code == 422
