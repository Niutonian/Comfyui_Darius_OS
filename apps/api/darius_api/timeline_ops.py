from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .database import Asset, Project, Timeline, TimelineVersion
from .timeline_audio import has_audio


class TimelineValidationError(ValueError):
    pass


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TimelineValidationError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise TimelineValidationError(f"{label} must be finite")
    return result


def validate_tracks(session: Session, timeline: Timeline, tracks: list[dict[str, Any]]) -> None:
    if len(tracks) > 64:
        raise TimelineValidationError("timeline cannot contain more than 64 tracks")
    asset_ids: set[str] = set()
    seen_track_ids: set[str] = set()
    allowed_kinds = {"video", "audio", "dialogue", "subtitle"}
    for track_index, track in enumerate(tracks):
        if not isinstance(track, dict) or track.get("kind") not in allowed_kinds:
            raise TimelineValidationError(f"track {track_index} has an invalid kind")
        track_id = str(track.get("id") or f"track-{track_index}")
        if track_id in seen_track_ids:
            raise TimelineValidationError("track ids must be unique")
        seen_track_ids.add(track_id)
        clips = track.get("clips")
        if not isinstance(clips, list) or len(clips) > 10_000:
            raise TimelineValidationError(f"track {track_index} clips must be a bounded list")
        for raw_index, clip in enumerate(clips):
            if not isinstance(clip, dict):
                raise TimelineValidationError(f"track {track_index} clip {raw_index} must be an object")
            _number(clip.get("timeline_in"), f"track {track_index} clip {raw_index} timeline_in")
        ordered_clips = sorted(clips, key=lambda item: float(item["timeline_in"]))
        previous_out = 0.0
        clip_ids: set[str] = set()
        for clip_index, clip in enumerate(ordered_clips):
            label = f"track {track_index} clip {clip_index}"
            clip_id = str(clip.get("id") or "")
            if not clip_id or clip_id in clip_ids:
                raise TimelineValidationError(f"{label} must have a unique non-empty id")
            clip_ids.add(clip_id)
            timeline_in = _number(clip.get("timeline_in"), f"{label} timeline_in")
            timeline_out = _number(clip.get("timeline_out"), f"{label} timeline_out")
            if timeline_in < 0 or timeline_out <= timeline_in:
                raise TimelineValidationError(f"{label} has an invalid timeline range")
            for field, maximum in (("volume", 1), ("fade_in", 86400), ("fade_out", 86400), ("audio_start", 86400), ("audio_end", 86400)):
                if field in clip:
                    value = _number(clip[field], f"{label} {field}")
                    if value < 0 or value > maximum:
                        raise TimelineValidationError(f"{label} {field} must be between 0 and {maximum}")
            if "audio_start" in clip or "audio_end" in clip:
                if "audio_start" not in clip or "audio_end" not in clip or clip["audio_end"] <= clip["audio_start"]:
                    raise TimelineValidationError(f"{label} audio envelope requires a valid start and end")
            if timeline_in + 1e-6 < previous_out:
                raise TimelineValidationError(f"track {track_index} clips cannot overlap")
            previous_out = timeline_out
            if track["kind"] in {"video", "audio"}:
                asset_id = clip.get("source_asset_id")
                if not isinstance(asset_id, str) or not asset_id:
                    raise TimelineValidationError(f"{label} requires source_asset_id")
                asset_ids.add(asset_id)
                source_in = _number(clip.get("source_in", 0), f"{label} source_in")
                source_out = _number(clip.get("source_out"), f"{label} source_out")
                if source_in < 0 or source_out <= source_in:
                    raise TimelineValidationError(f"{label} has an invalid source range")
                if abs((source_out - source_in) - (timeline_out - timeline_in)) > 0.05:
                    raise TimelineValidationError(f"{label} source and timeline durations must match")
            elif track["kind"] == "dialogue" and not str(clip.get("text") or "").strip():
                raise TimelineValidationError(f"{label} requires text")

    assets = {
        asset.id: asset
        for asset in session.scalars(select(Asset).where(Asset.id.in_(asset_ids)))
    } if asset_ids else {}
    if set(assets) != asset_ids or any(asset.project_id != timeline.project_id for asset in assets.values()):
        raise TimelineValidationError("all source assets must exist in the timeline project")
    for track in tracks:
        for clip in track["clips"]:
            asset_id = clip.get("source_asset_id")
            if not asset_id:
                continue
            asset = assets[asset_id]
            if track["kind"] == "video" and asset.kind not in {"image", "video"}:
                raise TimelineValidationError("video clips require image or video assets")
            if track["kind"] == "audio" and asset.kind not in {"audio", "video"}:
                raise TimelineValidationError("audio clips require audio or video assets")
            if asset.duration is not None and float(clip["source_out"]) > asset.duration + 0.05:
                raise TimelineValidationError("clip source range exceeds asset duration")


def _rational_time(seconds: float, rate: float) -> dict[str, Any]:
    return {"OTIO_SCHEMA": "RationalTime.1", "value": round(seconds * rate, 6), "rate": rate}


def _time_range(start: float, duration: float, rate: float) -> dict[str, Any]:
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": _rational_time(start, rate),
        "duration": _rational_time(duration, rate),
    }


def export_otio(
    session: Session, timeline: Timeline, version: TimelineVersion
) -> dict[str, Any]:
    project = session.get(Project, timeline.project_id)
    rate = project.default_fps if project else 24.0
    asset_ids = {
        clip["source_asset_id"]
        for track in version.tracks
        for clip in track.get("clips", [])
        if clip.get("source_asset_id")
    }
    assets = {asset.id: asset for asset in session.scalars(select(Asset).where(Asset.id.in_(asset_ids)))} if asset_ids else {}
    otio_tracks: list[dict[str, Any]] = []
    for track_index, track in enumerate(version.tracks):
        children: list[dict[str, Any]] = []
        cursor = 0.0
        for clip in sorted(track.get("clips", []), key=lambda item: item["timeline_in"]):
            start = float(clip["timeline_in"])
            duration = float(clip["timeline_out"]) - start
            if start > cursor:
                children.append({"OTIO_SCHEMA": "Gap.1", "source_range": _time_range(0, start - cursor, rate)})
            asset = assets.get(clip.get("source_asset_id"))
            if asset:
                child = {
                    "OTIO_SCHEMA": "Clip.2", "name": str(clip.get("id", "clip")),
                    "media_reference": {
                        "OTIO_SCHEMA": "ExternalReference.1", "target_url": Path(asset.path).resolve().as_uri(),
                        "available_range": None, "metadata": {"darius_asset_id": asset.id},
                    },
                    "source_range": _time_range(float(clip.get("source_in", 0)), duration, rate),
                    "metadata": {"darius": {key: value for key, value in clip.items() if key not in {"source_in", "source_out"}}},
                }
            else:
                child = {
                    "OTIO_SCHEMA": "Gap.1", "name": str(clip.get("id", "gap")),
                    "source_range": _time_range(0, duration, rate), "metadata": {"darius": clip},
                }
            children.append(child)
            cursor = float(clip["timeline_out"])
        otio_tracks.append({
            "OTIO_SCHEMA": "Track.1", "name": str(track.get("name") or f"{track['kind']}-{track_index + 1}"),
            "kind": "Video" if track["kind"] == "video" else "Audio", "children": children,
            "source_range": None, "effects": [], "markers": [], "metadata": {"darius_kind": track["kind"]},
        })
    return {
        "OTIO_SCHEMA": "Timeline.1", "name": timeline.name,
        "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": otio_tracks, "source_range": None, "effects": [], "markers": [], "metadata": {}},
        "global_start_time": None,
        "metadata": {"darius": {"timeline_id": timeline.id, "version_id": version.id, "version_number": version.version_number}},
    }


class FfmpegTimelineRenderer:
    def render(
        self,
        version: TimelineVersion,
        assets: dict[str, Asset],
        project: Project,
        output: Path,
        settings: Settings,
    ) -> Path:
        validate_tracks_for_render(version.tracks)
        video_track = next(track for track in version.tracks if track.get("kind") == "video" and track.get("clips"))
        clips = sorted(video_track["clips"], key=lambda item: item["timeline_in"])
        duration = max(float(clip["timeline_out"]) for track in version.tracks for clip in track.get("clips", []))
        width, height = (int(value) for value in project.default_resolution.lower().split("x", 1))
        args = [settings.ffmpeg_path, "-hide_banner", "-nostdin", "-y", "-filter_complex_threads", "2"]
        filters: list[str] = []
        labels: list[str] = []
        input_index = 0
        embedded: list[tuple[dict, int]] = []
        inspected: dict[str, bool] = {}

        def black(length: float) -> None:
            nonlocal input_index
            if length <= 0.000001:
                return
            args.extend(["-f", "lavfi", "-t", str(length), "-i", f"color=c=black:s={width}x{height}:r={project.default_fps}"])
            label = f"v{len(labels)}"
            filters.append(f"[{input_index}:v]trim=duration={length},setpts=PTS-STARTPTS,setsar=1,format=yuv420p[{label}]")
            labels.append(f"[{label}]")
            input_index += 1

        cursor = 0.0
        for clip in clips:
            black(max(0.0, float(clip["timeline_in"]) - cursor))
            asset = assets[clip["source_asset_id"]]
            length = float(clip["timeline_out"]) - float(clip["timeline_in"])
            if asset.kind == "image":
                args.extend(["-loop", "1", "-t", str(length), "-i", asset.path])
            else:
                args.extend(["-ss", str(clip.get("source_in", 0)), "-t", str(length), "-i", asset.path])
            label = f"v{len(labels)}"
            filters.append(
                f"[{input_index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={project.default_fps},"
                f"trim=duration={length},format=yuv420p,setpts=PTS-STARTPTS[{label}]"
            )
            labels.append(f"[{label}]")
            input_index += 1
            if asset.kind == "video" and not clip.get("muted"):
                asset_key = clip["source_asset_id"]
                if asset_key not in inspected:
                    inspected[asset_key] = has_audio(asset, settings)
                if inspected[asset_key]:
                    embedded.append((clip, input_index - 1))
            cursor = float(clip["timeline_out"])
        black(max(0.0, duration - cursor))
        filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[outv]")

        audio_labels: list[str] = []

        def add_audio(clip: dict, source_index: int) -> None:
            length = float(clip["timeline_out"]) - float(clip["timeline_in"])
            label = f"a{len(audio_labels)}"
            delay = round(float(clip["timeline_in"]) * 1000)
            source_in = float(clip.get("source_in", 0))
            envelope_in = float(clip.get("audio_start", source_in))
            envelope_out = float(clip.get("audio_end", clip.get("source_out", source_in + length)))
            gain = str(float(clip.get("volume", 1)))
            fade_in, fade_out = float(clip.get("fade_in", 0)), float(clip.get("fade_out", 0))
            if fade_in > 0:
                gain += f"*min(1,max(0,(t+{source_in}-{envelope_in})/{fade_in}))"
            if fade_out > 0:
                gain += f"*min(1,max(0,({envelope_out}-t-{source_in})/{fade_out}))"
            filters.append(
                f"[{source_index}:a:0]atrim=duration={length},asetpts=PTS-STARTPTS,"
                f"aresample=48000,aformat=channel_layouts=stereo,volume='{gain}':eval=frame,adelay={delay}:all=1[{label}]"
            )
            audio_labels.append(f"[{label}]")

        for clip, source_index in embedded:
            add_audio(clip, source_index)
        for track in version.tracks:
            if track.get("kind") != "audio":
                continue
            for clip in track.get("clips", []):
                if clip.get("muted"):
                    continue
                asset = assets[clip["source_asset_id"]]
                length = float(clip["timeline_out"]) - float(clip["timeline_in"])
                args.extend(["-ss", str(clip.get("source_in", 0)), "-t", str(length), "-i", asset.path])
                add_audio(clip, input_index)
                input_index += 1
        if audio_labels:
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={duration}[silence]")
            filters.append(
                f"[silence]{''.join(audio_labels)}amix=inputs={len(audio_labels) + 1}:duration=longest:normalize=0,"
                f"alimiter=limit=0.95:level=0,atrim=duration={duration}[outa]"
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        args.extend(["-filter_complex", ";".join(filters), "-map", "[outv]"])
        if audio_labels:
            args.extend(["-map", "[outa]", "-c:a", "aac", "-b:a", "192k"])
        args.extend([
            "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-t", str(duration), "-movflags", "+faststart", str(output),
        ])
        try:
            result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=3600, shell=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            output.unlink(missing_ok=True)
            raise RuntimeError(f"unable to run FFmpeg timeline render: {type(exc).__name__}") from exc
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            output.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg timeline render failed: {(result.stderr or result.stdout)[-2000:]}")
        return output


def validate_tracks_for_render(tracks: list[dict[str, Any]]) -> None:
    pictures = [track for track in tracks if track.get("kind") == "video" and track.get("clips")]
    if len(pictures) != 1:
        raise TimelineValidationError("This renderer requires exactly one picture track; multiple picture layers are not supported yet.")
    if any(track.get("kind") not in {"video", "audio"} and track.get("clips") for track in tracks):
        raise TimelineValidationError("Dialogue/subtitle tracks are not supported in this renderer yet; remove them before rendering.")
