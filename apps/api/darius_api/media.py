from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from .config import Settings


ALLOWED_UPLOAD_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".mp4", ".mov", ".mkv", ".webm",
    ".wav", ".mp3", ".flac", ".m4a", ".ogg",
    ".srt", ".vtt", ".txt", ".pdf", ".otio", ".json",
}


@dataclass(frozen=True, slots=True)
class IngestedMedia:
    path: Path
    content_hash: str
    kind: str
    mime_type: str
    width: int | None
    height: int | None
    duration: float | None
    fps: float | None
    sample_rate: int | None
    metadata: dict[str, Any]


def _ratio(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator) if float(denominator) else None
    return float(value)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _kind(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    prefix = mime.split("/", 1)[0]
    if prefix in {"image", "video", "audio"}:
        return prefix
    if path.suffix.lower() in {".srt", ".vtt"}:
        return "subtitle"
    if path.suffix.lower() in {".otio"}:
        return "timeline"
    return "document"


def _project_directory(settings: Settings, project_id: str, bucket: str) -> Path:
    root = (settings.data_dir / "projects").resolve()
    destination = (root / project_id / bucket).resolve()
    if root not in destination.parents:
        raise ValueError("project media path escaped configured root")
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def _probe(path: Path, settings: Settings) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [settings.ffprobe_path, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            shell=False,
        )
        return json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}


def _describe(path: Path, settings: Settings, original_filename: str) -> IngestedMedia:
    probe = _probe(path, settings)
    streams = probe.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    format_data = probe.get("format") or {}
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return IngestedMedia(
        path=path,
        content_hash=_hash(path),
        kind=_kind(path),
        mime_type=mime_type,
        width=video.get("width"),
        height=video.get("height"),
        duration=float(format_data["duration"]) if format_data.get("duration") else None,
        fps=_ratio(video.get("avg_frame_rate")),
        sample_rate=int(audio["sample_rate"]) if audio.get("sample_rate") else None,
        metadata={"ffprobe": probe, "original_filename": original_filename},
    )


def ingest_generated(source: Path, settings: Settings, project_id: str) -> IngestedMedia:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    destination_dir = _project_directory(settings, project_id, "generated")
    destination = destination_dir / f"{uuid.uuid4()}{source.suffix.lower()}"
    shutil.copy2(source, destination)
    return _describe(destination, settings, source.name)


def ingest_upload(
    stream: BinaryIO,
    filename: str,
    content_type: str | None,
    settings: Settings,
    project_id: str,
) -> IngestedMedia:
    suffix = Path(filename or "upload").suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise ValueError("unsupported upload file type")
    if content_type and not (
        content_type.startswith(("image/", "video/", "audio/", "text/"))
        or content_type in {"application/pdf", "application/json", "application/octet-stream"}
    ):
        raise ValueError("unsupported upload content type")
    destination_dir = _project_directory(settings, project_id, "sources")
    destination = destination_dir / f"{uuid.uuid4()}{suffix}"
    total = 0
    try:
        with destination.open("xb") as target:
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise ValueError("upload exceeds configured size limit")
                target.write(chunk)
        if total == 0:
            raise ValueError("upload is empty")
        return _describe(destination, settings, Path(filename).name)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
