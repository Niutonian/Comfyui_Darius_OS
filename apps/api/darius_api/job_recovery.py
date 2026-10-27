"""Conservative recovery for abandoned local generation jobs, never resubmission."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import urllib.request
from urllib.parse import urlparse

from sqlalchemy import func, select, update

from .database import Job, utcnow
from .diagnostics import record


def comfy_queue_idle(settings) -> bool:
    """Fail closed: an unavailable/unknown/busy queue is not evidence of idleness."""
    target = settings.comfyui_base_url.rstrip("/")
    parsed = urlparse(target)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password:
        return False

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(target + "/queue", timeout=2) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            return False
        queue = json.loads(raw)
        return (isinstance(queue, dict)
                and isinstance(queue.get("queue_running"), list)
                and isinstance(queue.get("queue_pending"), list)
                and not queue["queue_running"] and not queue["queue_pending"])
    except (OSError, ValueError):
        return False


def recover_abandoned_local_jobs(session_factory, settings, *, job_id=None,
                                 older_than=timedelta(minutes=5), queue_probe=None):
    """Resolve stale generation receipts only; no queue/interrupt/retry requests.

    A heartbeat/claim/cancellation compare-and-swap protects live workers that
    resume while ComfyUI is being inspected. Timeline and cloud jobs are excluded.
    Missing prompt IDs do not justify replaying a possibly submitted generation.
    """
    from .services import JobWorker, add_event, update_agent_task

    cutoff = utcnow() - older_than
    query = select(Job).where(
        Job.provider == "local-comfyui", Job.job_type == "generation",
        Job.status.in_(("running", "cancelling")),
        func.coalesce(Job.heartbeat_at, Job.started_at, Job.created_at) < cutoff,
    )
    if job_id is not None:
        query = query.where(Job.id == job_id)
    with session_factory() as session:
        snapshots = list(session.scalars(query.order_by(Job.created_at).limit(100)))
    if not snapshots or not (queue_probe or comfy_queue_idle)(settings):
        return []

    recovered = []
    for previous in snapshots:
        cancelled = previous.status == "cancelling" or previous.cancellation_requested
        now = utcnow()
        values = {
            "status": "cancelled" if cancelled else "failed", "completed_at": now,
            "status_message": "Cancellation completed after local worker stopped" if cancelled else "Local worker stopped; inspect ComfyUI history before retrying",
            "error_code": None if cancelled else "WorkerLost",
            "error_detail": None if cancelled else "The local worker heartbeat expired and ComfyUI's queue is idle. Check ComfyUI history and output files before explicitly retrying. No render was resubmitted.",
        }
        if cancelled:
            values.update(progress=0.0, cancellation_requested=True)
        with session_factory.begin() as session:
            result = session.execute(update(Job).where(
                Job.id == previous.id, Job.status == previous.status,
                Job.heartbeat_at == previous.heartbeat_at,
                Job.started_at == previous.started_at,
                Job.attempt_count == previous.attempt_count,
                Job.cancellation_requested == previous.cancellation_requested,
            ).values(**values).execution_options(synchronize_session=False))
            if result.rowcount != 1:
                continue
            current = session.get(Job, previous.id)
            JobWorker._finish_plan(session, current.id, current.status)
            update_agent_task(session, current)
            add_event(session, current.project_id, "job.recovered", "job", current.id,
                      {"status": current.status, "reason": "expired_local_worker", "resubmitted": False})
            recovered.append(current.id)
        record(settings, "worker", "info" if cancelled else "error", "abandoned_job_recovered",
               job_id=previous.id, project_id=previous.project_id,
               status=values["status"], last_heartbeat=previous.heartbeat_at, resubmitted=False)
    return recovered


async def recovery_loop(session_factory, settings, stop: asyncio.Event, *, interval=30):
    # Give a healthy child worker a full heartbeat cycle after API/PC resume.
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            try:
                await asyncio.to_thread(recover_abandoned_local_jobs, session_factory, settings)
            except Exception as exc:
                record(settings, "worker", "error", "job_recovery_check_failed", error_type=type(exc).__name__)
