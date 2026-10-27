from __future__ import annotations

import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .config import Settings
from .media import IngestedMedia, _describe, _project_directory


@dataclass(frozen=True, slots=True)
class DerivativeOutcome:
    derivative_type: str
    media: IngestedMedia | None = None
    error: str | None = None


def _run(args: Sequence[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), capture_output=True, text=True, check=False, timeout=timeout, shell=False
    )


def _derive(
    source: Path,
    destination: Path,
    derivative_type: str,
    ffmpeg_args: list[str],
    settings: Settings,
) -> DerivativeOutcome:
    try:
        result = _run(
            [settings.ffmpeg_path, "-hide_banner", "-nostdin", "-y", *ffmpeg_args, str(destination)],
            timeout=300,
        )
        if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
            destination.unlink(missing_ok=True)
            detail = (result.stderr or result.stdout or "FFmpeg produced no output")[-1000:].strip()
            return DerivativeOutcome(derivative_type, error=detail)
        media = _describe(destination, settings, source.name)
        return DerivativeOutcome(derivative_type, media=media)
    except (OSError, subprocess.TimeoutExpired) as exc:
        destination.unlink(missing_ok=True)
        return DerivativeOutcome(derivative_type, error=f"{type(exc).__name__}: {exc}")


def generate_derivatives(
    source: Path, kind: str, settings: Settings, project_id: str, *, thumbnail_only: bool = False
) -> tuple[DerivativeOutcome, ...]:
    """Create useful derivatives without ever replacing or modifying the source file."""
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if kind not in {"image", "video"}:
        return ()
    directory = _project_directory(settings, project_id, "derivatives")
    thumbnail = directory / f"{uuid.uuid4()}.jpg"
    thumbnail_args = [
        "-ss", "0", "-i", str(source), "-frames:v", "1", "-vf",
        "scale=480:-2:force_original_aspect_ratio=decrease", "-q:v", "3",
    ]
    outcomes = [_derive(source, thumbnail, "thumbnail", thumbnail_args, settings)]
    if thumbnail_only:
        return tuple(outcomes)
    if kind == "image":
        proxy = directory / f"{uuid.uuid4()}.jpg"
        proxy_args = [
            "-i", str(source), "-frames:v", "1", "-vf",
            "scale=1920:-2:force_original_aspect_ratio=decrease", "-q:v", "2",
        ]
    else:
        proxy = directory / f"{uuid.uuid4()}.mp4"
        proxy_args = [
            "-i", str(source), "-map", "0:v:0", "-map", "0:a?", "-vf",
            "scale=1280:-2:force_original_aspect_ratio=decrease",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", "-sn",
        ]
    outcomes.append(_derive(source, proxy, "proxy", proxy_args, settings))
    return tuple(outcomes)


def _numbers(pattern: str, text: str) -> list[float]:
    return [float(value) for value in re.findall(pattern, text)]


def _paired_intervals(text: str, prefix: str) -> list[dict[str, float]]:
    starts = _numbers(rf"{prefix}_start:\s*([0-9.eE+-]+)", text)
    ends = _numbers(rf"{prefix}_end:\s*([0-9.eE+-]+)", text)
    durations = _numbers(rf"{prefix}_duration:\s*([0-9.eE+-]+)", text)
    return [
        {
            "start": start,
            "end": ends[index],
            "duration": durations[index] if index < len(durations) else ends[index] - start,
        }
        for index, start in enumerate(starts)
        if index < len(ends)
    ]


def analyze_media(
    source: Path,
    kind: str,
    settings: Settings,
    *,
    silence_noise_db: float = -35.0,
    silence_duration: float = 0.5,
    black_pixel_threshold: float = 0.10,
    black_duration: float = 0.5,
    freeze_noise_db: float = -60.0,
    freeze_duration: float = 1.0,
    scene_threshold: float = 0.4,
) -> dict[str, Any]:
    """Return machine-readable media facts; unavailable streams/tools become warnings."""
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    facts: dict[str, Any] = {
        "silence": [], "black": [], "freeze": [], "scenes": [], "warnings": []
    }
    try:
        probe = _run(
            [settings.ffprobe_path, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)],
            timeout=30,
        )
        if probe.returncode == 0:
            facts["probe"] = json.loads(probe.stdout)
        else:
            facts["warnings"].append("ffprobe failed")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        facts["warnings"].append(f"ffprobe unavailable: {type(exc).__name__}")

    if kind in {"audio", "video"}:
        try:
            result = _run([
                settings.ffmpeg_path, "-hide_banner", "-nostdin", "-i", str(source),
                "-af", f"silencedetect=noise={silence_noise_db}dB:d={silence_duration}",
                "-vn", "-f", "null", "-",
            ], timeout=600)
            facts["silence"] = _paired_intervals(result.stderr, "silence")
            if result.returncode != 0 and "matches no streams" not in result.stderr:
                facts["warnings"].append("silence analysis failed")
        except (OSError, subprocess.TimeoutExpired) as exc:
            facts["warnings"].append(f"silence analysis unavailable: {type(exc).__name__}")

    if kind == "video":
        video_filter = (
            f"blackdetect=d={black_duration}:pix_th={black_pixel_threshold},"
            f"freezedetect=n={freeze_noise_db}dB:d={freeze_duration},"
            f"select=gt(scene\\,{scene_threshold}),showinfo"
        )
        try:
            result = _run([
                settings.ffmpeg_path, "-hide_banner", "-nostdin", "-i", str(source),
                "-vf", video_filter, "-an", "-f", "null", "-",
            ], timeout=600)
            facts["black"] = _paired_intervals(result.stderr, "black")
            facts["freeze"] = _paired_intervals(result.stderr, "freeze")
            facts["scenes"] = [
                {"time": value, "score": None}
                for value in _numbers(r"pts_time:([0-9.eE+-]+)", result.stderr)
            ]
            if result.returncode != 0:
                facts["warnings"].append("video analysis failed")
        except (OSError, subprocess.TimeoutExpired) as exc:
            facts["warnings"].append(f"video analysis unavailable: {type(exc).__name__}")
    return facts
