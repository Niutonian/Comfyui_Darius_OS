from dataclasses import replace
import math
import shutil
import subprocess
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from darius_api.database import Asset
from darius_api.main import create_app
from darius_api.timeline_audio import has_audio, waveform
from test_media_backend import create_project, settings_for


def test_audio_facts_use_known_streams_and_do_not_guess_failed_probes(tmp_path):
    settings = settings_for(tmp_path)
    assert has_audio(SimpleNamespace(kind="video", metadata_json={"ffprobe": {"streams": [{"codec_type": "video"}]}}), settings) is False
    assert has_audio(SimpleNamespace(kind="video", metadata_json={"ffprobe": {"streams": [{"codec_type": "audio"}]}}), settings) is True
    with pytest.raises(RuntimeError, match="FFprobe"):
        has_audio(SimpleNamespace(kind="video", path="missing.mp4"), settings)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="native FFmpeg required")
def test_waveform_is_real_bounded_cached_and_project_guarded(tmp_path, monkeypatch):
    settings = replace(settings_for(tmp_path), ffmpeg_path=shutil.which("ffmpeg"), ffprobe_path=shutil.which("ffprobe"))
    app = create_app(settings)
    with TestClient(app) as client:
        project = create_project(client)
        foreign = create_project(client, "Foreign")
        source = settings.data_dir / "wave.wav"
        subprocess.run([settings.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(source)], check=True, timeout=20)
        (tmp_path / "outside.wav").write_bytes(source.read_bytes())
        with app.state.session_factory.begin() as session:
            session.add(Asset(id="sound", project_id=project, kind="audio", role="source", provider="fixture", path=str(source), content_hash="fixture", mime_type="audio/wav", duration=1, parent_asset_ids=[], metadata_json={"ffprobe": {"streams": [{"codec_type": "audio"}]}}))
            session.add(Asset(id="outside", project_id=project, kind="audio", role="source", provider="fixture", path=str(tmp_path / "outside.wav"), content_hash="fixture", mime_type="audio/wav", parent_asset_ids=[], metadata_json={}))
        path = "/api/v1/assets/sound/audio-preview"
        assert client.get(path, params={"project_id": foreign}).status_code == 404
        assert client.get(path).status_code == 422
        response = client.get(path, params={"project_id": project})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["has_audio"] is True and data["partial"] is False
        assert data["duration"] == pytest.approx(1, abs=.02)
        assert 0 < len(data["peaks"]) <= 512
        assert all(math.isfinite(peak) and 0 <= peak <= 1 for peak in data["peaks"])
        assert max(data["peaks"]) > .05
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("cached waveform should not decode twice"))
        assert client.get(path, params={"project_id": project}).json() == data
        assert client.get("/api/v1/assets/outside/audio-preview", params={"project_id": project}).status_code == 404


def test_versions_reject_invalid_audio_controls(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        project = create_project(client)
        image = client.post("/api/v1/assets/upload", data={"project_id": project}, files={"file": ("still.png", b"fixture", "image/png")}).json()
        timeline = client.post("/api/v1/timelines", json={"project_id": project, "name": "Cut"}).json()
        clip = {"id": "c", "source_asset_id": image["id"], "source_in": 0, "source_out": 1, "timeline_in": 0, "timeline_out": 1}
        for patch in ({"volume": 2}, {"fade_in": -1}, {"fade_out": "0;malicious"}, {"audio_start": 0}, {"audio_start": 1, "audio_end": 0}):
            response = client.post(f"/api/v1/timelines/{timeline['id']}/versions", json={"tracks": [{"kind": "video", "clips": [{**clip, **patch}]}]})
            assert response.status_code in {409, 422}, response.text
