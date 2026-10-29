from __future__ import annotations

import argparse
import time
import hashlib
import os
import sys
from pathlib import Path
from sqlalchemy import select

def source_revision(directory: Path | None = None) -> tuple:
    """Cheap local update marker; never reload Python modules during a render."""
    directory = directory or Path(__file__).resolve().parent
    return tuple((path.name, path.stat().st_mtime_ns, path.stat().st_size)
                 for path in sorted(directory.glob('*.py')))


LOADED_SOURCE_REVISION = source_revision()

from .config import Settings
from .database import Base, make_engine, make_session_factory, Job
from .providers import ComfyMcpProvider
from .services import JobWorker, register_workflows
from .workflows import WorkflowRegistry


def build_worker(settings: Settings | None = None) -> JobWorker:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    from .diagnostics import record
    record(settings, "worker", "info", "worker_started")
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    registry = WorkflowRegistry(settings.workflow_definitions_dir, include_bfl=bool(settings.bfl_api_key))
    registry.load()
    register_workflows(session_factory, registry)
    return JobWorker(session_factory, registry, settings, ComfyMcpProvider(settings))


def main() -> int:
    parser = argparse.ArgumentParser(description="Darius persistent generation worker")
    parser.add_argument("--once", action="store_true", help="claim at most one job and exit")
    parser.add_argument("--job-id", help="claim only this job and exit without recovering or draining other jobs")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--canvas-queue", action="store_true", help="single shared Canvas dispatcher for this database")
    args = parser.parse_args()

    worker = build_worker()
    if args.canvas_queue:
        # The OS releases this lock after a crash. Preview databases cannot
        # drain the live queue; GPU capacity remains shared across databases.
        key = hashlib.sha256(worker.settings.database_url.encode()).hexdigest()[:20]
        path = Path(worker.settings.data_dir) / ("canvas-dispatcher-" + key + ".lock")
        with path.open("a+b") as handle:
            handle.seek(0, 2)
            if not handle.tell(): handle.write(b"0"); handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return 0
            while True:
                if source_revision() != LOADED_SOURCE_REVISION:
                    # run_once is synchronous, so this point is always between jobs.
                    # Leave the dispatcher lock before replacing the process.
                    break
                with worker.session_factory() as session:
                    job_id = session.scalar(select(Job.id).where(Job.status == "queued", Job.provider == "local-comfyui", Job.job_type == "generation",
                        (Job.input_payload["canvas_generation_id"].as_string().is_not(None)) | (Job.input_payload["worker_ready"].as_boolean() == True))
                        .order_by(Job.created_at, Job.id).limit(1))
                if not job_id or not worker.run_once(job_id): time.sleep(args.poll_seconds)
        os.execv(sys.executable, [sys.executable, '-m', 'darius_api.worker', *sys.argv[1:]])
        return 0
    if args.job_id:
        # A targeted worker waits for shared capacity instead of losing its
        # wake-up when another Canvas or external ComfyUI job occupies it.
        while not worker.run_once(args.job_id):
            with worker.session_factory() as session:
                row = session.get(Job, args.job_id)
                if not row or row.status != "queued": break
            time.sleep(args.poll_seconds)
        return 0
    worker.recover_abandoned()
    if args.once:
        worker.run_once()
        return 0
    while True:
        if worker.run_once() is None:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
