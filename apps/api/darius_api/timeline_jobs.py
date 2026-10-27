"""Launch only an explicitly approved FFmpeg timeline job, never the general queue."""
from datetime import datetime, timezone

from sqlalchemy import text

from .database import Job, Timeline, TimelineVersion, utcnow
from .services import RequestError, add_event, new_id
from .timeline_ops import TimelineValidationError, validate_tracks, validate_tracks_for_render


def start_timeline_job(session_factory, settings, job_id):
    now, token = utcnow(), new_id()
    with session_factory.begin() as session:
        # Serialize the short launch reservation across requests/devices. The worker's
        # existing atomic claim is still the final guard against duplicate execution.
        session.execute(text("BEGIN IMMEDIATE"))
        job = session.get(Job, job_id)
        if job is None:
            raise RequestError("job does not exist")
        payload = dict(job.input_payload or {})
        if job.job_type != "timeline_render" or job.provider != "ffmpeg" or payload.get("approved") is not True:
            raise RequestError("Only an explicitly approved FFmpeg timeline render can be started here")
        timeline = session.get(Timeline, payload.get("timeline_id"))
        version = session.get(TimelineVersion, payload.get("timeline_version_id"))
        if not timeline or not version or timeline.project_id != job.project_id or version.timeline_id != timeline.id or version.state != "accepted":
            raise RequestError("The approved timeline version does not belong to this render project")
        if job.cancellation_requested or job.status in {"cancelled", "cancelling", "failed"}:
            raise RequestError("Use Retry for a failed or cancelled render")
        if job.status in {"running", "completed"}:
            return job
        if job.status != "queued":
            raise RequestError(f"Render cannot start from {job.status}")
        try:
            validate_tracks(session, timeline, list(version.tracks))
            validate_tracks_for_render(list(version.tracks))
        except TimelineValidationError as exc:
            raise RequestError(str(exc)) from exc
        previous = payload.get("timeline_worker_start", {})
        if isinstance(previous, dict) and previous.get("state") in {"starting", "started"}:
            try:
                requested = datetime.fromisoformat(previous["requested_at"])
                if requested.tzinfo is None:
                    requested = requested.replace(tzinfo=timezone.utc)
                if 0 <= (now - requested).total_seconds() < 30:
                    return job
            except (KeyError, TypeError, ValueError):
                pass
        job.input_payload = {**payload, "timeline_worker_start": {"token": token, "requested_at": now.isoformat(), "state": "starting"}}
        job.status_message = "Starting CPU render worker for this approved cut"
        add_event(session, job.project_id, "job.worker_start_requested", "job", job.id)

    # Spawn after committing, so the child sees the queued job and no write lock is held.
    error = None
    try:
        from .local_render import launch_local_job
        launch_local_job(settings, job_id)
    except OSError as exc:
        error = exc
        from .diagnostics import record
        record(settings, "worker", "error", "timeline_worker_start_failed", job_id=job_id, error=str(exc))
    with session_factory.begin() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise RequestError("job does not exist")
        attempt = job.input_payload.get("timeline_worker_start", {})
        # Do not overwrite progress/completion/cancellation from a fast child or another client.
        if job.status == "queued" and attempt.get("token") == token:
            job.input_payload = {**job.input_payload, "timeline_worker_start": {**attempt, "state": "failed" if error else "started"}}
            job.status_message = "Render worker could not start. Use Start render in Background jobs to retry." if error else "CPU render worker started; waiting to claim this cut"
            add_event(session, job.project_id, "job.worker_start_failed" if error else "job.worker_started", "job", job.id)
        return job
