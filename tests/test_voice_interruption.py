import json
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_local_voice import voice


def recognition(text, confidence=0.99):
    return {"text": text, "result": [{"word": word, "conf": confidence} for word in text.split()]}


@pytest.mark.parametrize("text,expected", [
    ("darius stop", True), ("hey darius stop", True), ("darius wait", True),
    ("stop", False), ("darius", False), ("we told darius stop", False),
    ("darius stop then generate a video", False), ("various stop", False),
])
def test_explicit_addressed_stop(text, expected):
    assert voice.detected_interruption(recognition(text), recognition(text)) is expected
    assert not voice.detected_interruption(recognition(text, 0.5), recognition(text))
    assert not voice.detected_interruption(recognition(text), recognition("unrelated speech"))


def test_interrupt_mode_ignores_echo_and_never_transcribes_playback(monkeypatch):
    class Recognizer:
        def __init__(self, *_): self.text = ""
        def SetWords(self, *_): pass
        def Reset(self): self.text = ""
        def AcceptWaveform(self, pcm):
            self.text = pcm.decode().strip()
            return True
        def Result(self): return json.dumps(recognition(self.text))
        def FinalResult(self): return self.Result()
    calls = []
    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(KaldiRecognizer=Recognizer))
    monkeypatch.setattr(voice, "get_recognition_model", lambda: object())
    monkeypatch.setattr(voice, "transcribe", lambda pcm: calls.append(pcm) or "My follow-up")
    monkeypatch.setattr(voice, "trailing_silence", lambda *args, **kwargs: True)
    with TestClient(voice.app).websocket_connect("/listen", headers={"origin": "http://127.0.0.1:3000"}) as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"mode": "interrupt", "epoch": 4})
        ws.send_bytes(b"ordinary reply")
        ws.send_bytes(b"darius stop ")
        assert ws.receive_json() == {"type": "interrupt", "epoch": 4}
        assert calls == []
        ws.send_json({"mode": "conversation", "epoch": 5})
        ws.send_bytes(b"followup")
        assert ws.receive_json()["type"] == "partial"
        assert ws.receive_json()["type"] == "hold"
        assert ws.receive_json() == {"type": "final", "text": "My follow-up", "epoch": 5}
        assert len(calls) == 1


def test_bundled_model_name_spelling_is_not_a_fuzzy_wake_match():
    assert voice.detected_interruption(recognition("darius stop"), recognition("darrius stop"))
    assert not voice.detected_interruption(recognition("darius stop"), recognition("various stop"))
    assert not voice.detected_interruption(recognition("darius stop"), recognition("darius story"))
