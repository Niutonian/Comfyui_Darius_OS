"""CPU-only fixtures: real render parity, no user media, model calls or GPU."""
import array
import json
import math
import shutil
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest

from darius_api.timeline_ops import FfmpegTimelineRenderer, TimelineValidationError, validate_tracks_for_render
from test_media_backend import settings_for


def test_render_rejects_unsupported_layers_instead_of_dropping_them():
    video = {"kind": "video", "clips": [{"id": "v"}]}
    with pytest.raises(TimelineValidationError, match="exactly one"):
        validate_tracks_for_render([video, video])
    with pytest.raises(TimelineValidationError, match="subtitle"):
        validate_tracks_for_render([video, {"kind": "subtitle", "clips": [{"text": "hello"}]}])


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="native FFmpeg required")
def test_real_picture_sequence_preserves_trims_gaps_still_and_delayed_audio(tmp_path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    def run(*args):
        return subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *map(str, args)], capture_output=True, check=True, timeout=30)
    for color in ("red", "blue"):
        run("-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=20:d=1.5", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", tmp_path / f"{color}.mp4")
    run("-f", "lavfi", "-i", "color=c=green:s=160x90", "-frames:v", "1", "-threads", "1", tmp_path / "green.png")
    run("-f", "lavfi", "-i", "sine=frequency=440:duration=2", tmp_path / "tone.wav")
    assets = {key: SimpleNamespace(kind=kind, path=str(tmp_path / name)) for key, kind, name in [("red", "video", "red.mp4"), ("blue", "video", "blue.mp4"), ("green", "image", "green.png"), ("tone", "audio", "tone.wav")]}
    def clip(key, source_in, length, start):
        return {"id": key, "source_asset_id": key, "source_in": source_in, "source_out": source_in + length, "timeline_in": start, "timeline_out": start + length}
    tracks = [{"kind": "video", "clips": [clip("red", .5, 1, 0), clip("blue", 0, .5, 1.5), clip("green", 0, .5, 2)]}, {"kind": "audio", "clips": [clip("tone", .25, 1, .5)]}]
    output = tmp_path / "assembly.mp4"
    settings = replace(settings_for(tmp_path), ffmpeg_path=ffmpeg, ffprobe_path=ffprobe)
    FfmpegTimelineRenderer().render(SimpleNamespace(tracks=tracks), assets, SimpleNamespace(default_resolution="160x90", default_fps=20), output, settings)
    probe = json.loads(subprocess.run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(output)], capture_output=True, text=True, check=True).stdout)
    assert abs(float(probe["format"]["duration"]) - 2.5) < .1
    assert {stream["codec_type"] for stream in probe["streams"]} == {"video", "audio"}
    def pixel(at):
        return list(run("-ss", at, "-i", output, "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1").stdout)
    red, black, blue, green = [pixel(at) for at in (.25, 1.25, 1.75, 2.25)]
    assert red[0] > 180 and red[2] < 30
    assert max(black) < 15
    assert blue[2] > 180 and blue[0] < 30
    assert green[1] > 80 and green[0] < 30
    def rms(at):
        values = array.array("f", run("-ss", at, "-i", output, "-t", .1, "-vn", "-ac", "1", "-f", "f32le", "pipe:1").stdout)
        return math.sqrt(sum(value * value for value in values) / len(values))
    assert rms(.15) < .002
    assert rms(.8) > .02
    assert rms(1.9) < .002


def test_muted_audio_is_not_added_to_the_mix(tmp_path, monkeypatch):
    captured = []
    output = tmp_path / "muted.mp4"
    def fake(args, **kwargs):
        captured.extend(args); output.write_bytes(b"fixture"); return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake)
    clip = {"id": "v", "source_asset_id": "image", "source_in": 0, "source_out": 1, "timeline_in": 0, "timeline_out": 1}
    tracks = [{"kind": "video", "clips": [clip]}, {"kind": "audio", "clips": [{**clip, "id": "muted", "source_asset_id": "sound", "muted": True}]}]
    FfmpegTimelineRenderer().render(SimpleNamespace(tracks=tracks), {"image": SimpleNamespace(kind="image", path="image.png")}, SimpleNamespace(default_resolution="160x90", default_fps=20), output, settings_for(tmp_path))
    assert "sound" not in captured
    assert "[outa]" not in captured


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="native FFmpeg required")
def test_embedded_audio_volume_fades_and_split_continuity(tmp_path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    def run(*args):
        return subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *map(str, args)], capture_output=True, check=True, timeout=30)
    source = tmp_path / "talk.mp4"
    run("-f", "lavfi", "-i", "color=c=red:s=160x90:r=20:d=4", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-af", "volume=0:enable='lt(t,1)'", "-c:v", "libx264", "-threads", "1", "-c:a", "aac", "-shortest", source)
    settings = replace(settings_for(tmp_path), ffmpeg_path=ffmpeg, ffprobe_path=ffprobe)
    asset = SimpleNamespace(kind="video", path=str(source))
    clip = {"id": "v", "source_asset_id": "talk", "source_in": .5, "source_out": 3.5, "timeline_in": 0, "timeline_out": 3, "volume": .5, "fade_in": 1, "fade_out": 1}
    renderer = FfmpegTimelineRenderer()
    project = SimpleNamespace(default_resolution="160x90", default_fps=20)
    def render(clips, name):
        output = tmp_path / name
        renderer.render(SimpleNamespace(tracks=[{"kind": "video", "clips": clips}]), {"talk": asset}, project, output, settings)
        return output
    def rms(path, at):
        values = array.array("f", run("-ss", at, "-i", path, "-t", .1, "-vn", "-ac", "1", "-f", "f32le", "pipe:1").stdout)
        return math.sqrt(sum(value * value for value in values) / len(values))
    full = render([clip], "full.mp4")
    level = rms(full, 1.5)
    assert .025 < level < .06
    assert rms(full, .1) < level * .3
    assert rms(full, 2.8) < level * .3
    assert rms(full, .3) < .002
    assert rms(full, .65) > .01  # Source trim moves the one-second audio onset to .5s.
    moved = render([{**clip, "timeline_in": 1, "timeline_out": 4}], "moved.mp4")
    assert rms(moved, .65) < .002
    assert rms(moved, 1.65) > .01
    # A split inside the original fade must not restart it on the second piece.
    envelope = {"audio_start": .5, "audio_end": 3.5}
    split = render([{**clip, **envelope, "source_out": 1, "timeline_out": .5}, {**clip, **envelope, "id": "right", "source_in": 1, "timeline_in": .5}], "split.mp4")
    for at in (.2, .7, 1.5, 2.8):
        assert rms(split, at) == pytest.approx(rms(full, at), rel=.2, abs=.003)
    muted = render([{**clip, "muted": True}], "muted-video.mp4")
    probe = json.loads(subprocess.run([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(muted)], capture_output=True, text=True, check=True).stdout)
    assert all(stream["codec_type"] != "audio" for stream in probe["streams"])
