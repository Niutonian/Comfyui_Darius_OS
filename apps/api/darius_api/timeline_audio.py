"""CPU-only audio facts and bounded waveform previews for immutable managed assets."""
from __future__ import annotations

import array
from collections import OrderedDict
import json
import math
from pathlib import Path
import subprocess
import sys
from threading import Lock

from .config import Settings

_cache: OrderedDict[tuple, dict] = OrderedDict()
_lock = Lock()  # One decoder at a time; no GPU or unbounded browser downloads.


def has_audio(asset, settings: Settings) -> bool:
    if asset.kind not in {"video", "audio"}:
        return False
    probe = (getattr(asset, "metadata_json", None) or {}).get("ffprobe", {})
    streams = probe.get("streams") if isinstance(probe, dict) else None
    if not isinstance(streams, list):
        try:
            result = subprocess.run(
                [settings.ffprobe_path, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "json", str(asset.path)],
                capture_output=True, text=True, check=False, timeout=10, shell=False,
            )
            if result.returncode != 0:
                raise RuntimeError("Could not inspect source audio. Check that the media and FFprobe are available.")
            streams = json.loads(result.stdout).get("streams", [])
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            raise RuntimeError("Could not inspect source audio. Check that FFprobe is available and retry.") from exc
    return any(isinstance(stream, dict) and stream.get("codec_type") == "audio" for stream in streams)


def waveform(asset, settings: Settings) -> dict:
    path = Path(asset.path).resolve(strict=True)
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns, settings.ffmpeg_path, settings.ffprobe_path)
    if not _lock.acquire(timeout=2):
        raise RuntimeError("Another waveform is being decoded. Retry in a moment.")
    try:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        available = has_audio(asset, settings)
        result = {"has_audio": available, "peaks": [], "duration": 0.0, "partial": False}
        if available:
            try:
                decoded = subprocess.run(
                    [settings.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", "1", "-i", str(path), "-map", "0:a:0", "-t", "1800", "-vn", "-ac", "1", "-ar", "2000", "-f", "s16le", "pipe:1"],
                    capture_output=True, check=False, timeout=12, shell=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError("Waveform preview could not be decoded. Playback and editing are still available.") from exc
            if decoded.returncode != 0:
                raise RuntimeError("Waveform preview could not be decoded. Playback and editing are still available.")
            samples = array.array("h", decoded.stdout[:7_200_000])
            if sys.byteorder != "little":
                samples.byteswap()
            step = max(1, math.ceil(len(samples) / 512))
            peaks = [round(max(abs(value) for value in samples[start:start + step]) / 32768, 4) for start in range(0, len(samples), step)]
            result = {"has_audio": True, "peaks": peaks, "duration": len(samples) / 2000, "partial": len(samples) >= 3_600_000 or bool(asset.duration and asset.duration > 1800)}
        _cache[key] = result
        while len(_cache) > 64:
            _cache.popitem(last=False)
        return result
    finally:
        _lock.release()
