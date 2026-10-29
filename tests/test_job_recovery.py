"""Recovery never submits, interrupts, or requeues a local generation."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from darius_api.config import Settings
from darius_api.database import (
    ActionPlan, ActionPlanTransition, Asset, Base, Conversation, Job, Message,
    Project, ProjectEvent, make_engine, make_session_factory, utcnow,
)
from darius_api import job_recovery
from darius_api import services
from darius_api.main import create_app
from darius_api.providers import ProviderResult
from darius_api.services import JobWorker, enqueue_request, register_workflows
from darius_api.workflows import WorkflowRegistry
from offline_fixtures import offline_definitions


@pytest.fixture
def recovery_db(tmp_path):
    settings = Settings(
        repository_root=tmp_path, data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'recovery.db').as_posix()}",
        workflow_definitions_dir=offline_definitions(tmp_path),
        comfyui_base_url="http://127.0.0.1:1",
    )
    settings.ensure_directories()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    registry = WorkflowRegistry(settings.workflow_definitions_dir)
    registry.load()
    register_workflows(factory, registry)
    with factory.begin() as session:
        session.add(Project(id="project", name="Recovery"))
    yield SimpleNamespace(settings=settings, factory=factory, registry=registry)
    engine.dispose()


def seed(db, **overrides):
    values = dict(id="job", project_id="project", provider="local-comfyui",
                  status="cancelling", cancellation_requested=True, input_payload={},
                  started_at=utcnow() - timedelta(minutes=11),
                  heartbeat_at=utcnow() - timedelta(minutes=10))
    values.update(overrides)
    with db.factory.begin() as session:
        session.add(Job(**values))
    return values["id"]


def recover(db, **kwargs):
    return job_recovery.recover_abandoned_local_jobs(
        db.factory, db.settings, queue_probe=lambda _: True, **kwargs)


def test_stale_cancellation_updates_receipt_plan_chat_and_events_once(recovery_db):
    db = recovery_db
    seed(db, input_payload={"local_render_message_id": "user"})
    with db.factory.begin() as session:
        session.add(Conversation(id="conversation", project_id="project"))
        session.flush()
        session.add_all([
            Message(id="user", conversation_id="conversation", role="user", content="Render",
                    metadata_json={"task": {"engine": "langgraph", "state": "running"}}),
            Message(id="reply", conversation_id="conversation", role="assistant", content="Rendering",
                    metadata_json={"reply_to": "user"}),
            ActionPlan(id="plan", project_id="project", workflow_definition_id="minimax-h3-seamless-core",
                       request_text="Render", provider="local-comfyui", inputs={}, expected_output={},
                       state="running", job_id="job"),
        ])
    assert recover(db) == ["job"]
    assert recover(db) == []
    with db.factory() as session:
        job = session.get(Job, "job")
        assert job.status == "cancelled"
        assert job.completed_at and job.progress == 0 and job.cancellation_requested
        assert job.error_code is None and job.output_asset_ids == []
        assert session.get(ActionPlan, "plan").state == "cancelled"
        transitions = list(session.scalars(select(ActionPlanTransition)))
        assert len(transitions) == 1 and transitions[0].to_state == "cancelled"
        user_task = session.get(Message, "user").metadata_json["task"]
        assert user_task["state"] == "cancelled"
        assert session.get(Message, "reply").metadata_json["task"] == user_task
        events = list(session.scalars(select(ProjectEvent).where(ProjectEvent.event_type == "job.recovered")))
        assert len(events) == 1 and events[0].payload["resubmitted"] is False


def test_abandoned_running_job_fails_instead_of_replaying(recovery_db):
    seed(recovery_db, status="running", cancellation_requested=False, external_job_id="saved-prompt")
    assert recover(recovery_db) == ["job"]
    with recovery_db.factory() as session:
        job = session.get(Job, "job")
        assert job.status == "failed" and job.error_code == "WorkerLost"
        assert job.external_job_id == "saved-prompt" and job.attempt_count == 0
        assert "No render was resubmitted" in job.error_detail
    with TestClient(create_app(recovery_db.settings)) as client:
        run = client.get("/api/v1/jobs/job/run").json()
        assert run["recovery_action"] == "inspect_provider_queue"
        assert run["can_retry"] is False


@pytest.mark.parametrize("overrides", [
    {"status": "queued"}, {"status": "completed"}, {"status": "failed"},
    {"status": "cancelled"}, {"provider": "bfl"}, {"job_type": "timeline_render"},
    {"heartbeat_at": utcnow},
    {"heartbeat_at": None, "started_at": utcnow},
    {"heartbeat_at": None, "started_at": None, "created_at": utcnow},
])
def test_out_of_scope_and_healthy_jobs_are_not_probed(recovery_db, overrides):
    # Collection may precede execution by more than the recovery stale threshold.
    seed(recovery_db, **{key: value() if callable(value) else value for key, value in overrides.items()})
    probe = MagicMock(side_effect=AssertionError("Must not inspect queue"))
    assert job_recovery.recover_abandoned_local_jobs(
        recovery_db.factory, recovery_db.settings, queue_probe=probe) == []
    probe.assert_not_called()


@pytest.mark.parametrize("status", ["running", "cancelling"])
def test_busy_or_unavailable_queue_leaves_stale_job_alone(recovery_db, status):
    seed(recovery_db, status=status)
    assert job_recovery.recover_abandoned_local_jobs(
        recovery_db.factory, recovery_db.settings, queue_probe=lambda _: False) == []
    with recovery_db.factory() as session:
        assert session.get(Job, "job").status == status


@pytest.mark.parametrize("change", ["heartbeat", "cancellation", "claim", "completion"])
def test_concurrent_updates_during_probe_win_over_recovery(recovery_db, change):
    db = recovery_db
    seed(db, status="running", cancellation_requested=False)
    def probe(_):
        with db.factory.begin() as session:
            job = session.get(Job, "job")
            if change == "heartbeat":
                job.heartbeat_at = utcnow()
            elif change == "cancellation":
                job.cancellation_requested, job.status = True, "cancelling"
            elif change == "claim":
                job.attempt_count += 1
            else:
                job.status = "completed"
        return True
    assert job_recovery.recover_abandoned_local_jobs(db.factory, db.settings, queue_probe=probe) == []
    with db.factory() as session:
        assert session.get(Job, "job").error_code is None
    if change == "cancellation":
        assert recover(db) == ["job"]
        with db.factory() as session:
            assert session.get(Job, "job").status == "cancelled"


def test_targeted_recovery_does_not_change_other_stale_jobs(recovery_db):
    seed(recovery_db)
    seed(recovery_db, id="other")
    assert recover(recovery_db, job_id="job") == ["job"]
    with recovery_db.factory() as session:
        assert session.get(Job, "other").status == "cancelling"


def test_persistent_worker_cannot_bypass_local_queue_safety(recovery_db, monkeypatch):
    seed(recovery_db, status="running", cancellation_requested=False)
    worker = JobWorker(recovery_db.factory, recovery_db.registry, recovery_db.settings, None)
    monkeypatch.setattr(job_recovery, "comfy_queue_idle", lambda _: False)
    assert worker.recover_abandoned() == 0
    with recovery_db.factory() as session:
        assert session.get(Job, "job").status == "running"
    monkeypatch.setattr(job_recovery, "comfy_queue_idle", lambda _: True)
    assert worker.recover_abandoned() == 1
    with recovery_db.factory() as session:
        assert session.get(Job, "job").status == "failed"


@pytest.mark.parametrize("raises", [False, True])
def test_late_worker_result_or_error_does_not_overwrite_recovered_receipt(recovery_db, raises):
    db = recovery_db
    job = enqueue_request(db.factory, db.registry, "project", "minimax-h3-seamless-core",
                          "Render", {"script": "Recovery fixture."}, True)
    class LateProvider:
        def execute(self, *args):
            with db.factory.begin() as session:
                active = session.get(Job, job.id)
                active.status, active.cancellation_requested = "cancelling", True
                active.heartbeat_at = utcnow() - timedelta(minutes=10)
            assert recover(db, job_id=job.id) == [job.id]
            if raises:
                raise RuntimeError("Late provider failure")
            return ProviderResult("late-prompt", (db.settings.data_dir / "must-not-be-ingested.png",), {}, True)
    worker = JobWorker(db.factory, db.registry, db.settings, LateProvider())
    assert worker.run_once(job.id) == job.id
    with db.factory() as session:
        active = session.get(Job, job.id)
        assert active.status == "cancelled" and active.error_code is None
        assert active.external_job_id is None and active.output_asset_ids == []
        assert list(session.scalars(select(Asset))) == []


def test_cancelling_worker_keeps_heartbeating_without_overwriting_cancellation_label(recovery_db, monkeypatch):
    db = recovery_db
    job = enqueue_request(db.factory, db.registry, "project", "minimax-h3-seamless-core",
                          "Render", {"script": "Recovery fixture."}, True)
    tick = []
    class StopFlag:
        def __init__(self):
            self.waits = 0
        def wait(self, seconds):
            assert seconds == 15
            self.waits += 1
            return self.waits > 1
        def set(self):
            pass
    class InlineThread:
        def __init__(self, *, target, **kwargs):
            tick.append(target)
        def start(self):
            pass
        def join(self, **kwargs):
            pass
    monkeypatch.setattr(services, "threading", SimpleNamespace(Event=StopFlag, Thread=InlineThread))
    class CancellingProvider:
        def execute(self, *args):
            with db.factory.begin() as session:
                active = session.get(Job, job.id)
                active.status, active.cancellation_requested = "cancelling", True
                active.status_message = "Cancellation requested"
                active.heartbeat_at = utcnow() - timedelta(minutes=10)
            tick[0]()  # One real heartbeat body, without sleeping or starting a thread.
            with db.factory() as session:
                active = session.get(Job, job.id)
                assert (utcnow().replace(tzinfo=None) - active.heartbeat_at).total_seconds() < 5
                assert active.status_message == "Cancellation requested"
            assert recover(db, job_id=job.id) == []
            return ProviderResult("prompt", (), {}, True)
    worker = JobWorker(db.factory, db.registry, db.settings, CancellingProvider())
    assert worker.run_once(job.id) == job.id
    with db.factory() as session:
        assert session.get(Job, job.id).status == "cancelled"


@pytest.mark.parametrize("payload,expected", [
    ({"queue_running": [], "queue_pending": []}, True),
    ({"queue_running": [[1]], "queue_pending": []}, False),
    ({"queue_running": [], "queue_pending": [[1]]}, False),
    ({}, False), ([], False), ({"queue_running": None, "queue_pending": []}, False),
])
def test_queue_probe_requires_explicit_idle_lists(recovery_db, monkeypatch, payload, expected):
    opener = MagicMock()
    response = opener.open.return_value.__enter__.return_value
    response.read.return_value = json.dumps(payload).encode()
    monkeypatch.setattr(job_recovery.urllib.request, "build_opener", lambda *args: opener)
    assert job_recovery.comfy_queue_idle(recovery_db.settings) is expected
    opener.open.assert_called_once_with("http://127.0.0.1:1/queue", timeout=2)
    response.read.assert_called_once_with(1_000_001)


@pytest.mark.parametrize("error", [TimeoutError(), OSError(), ValueError()])
def test_queue_probe_failure_is_not_idle(recovery_db, monkeypatch, error):
    opener = MagicMock()
    opener.open.side_effect = error
    monkeypatch.setattr(job_recovery.urllib.request, "build_opener", lambda *args: opener)
    assert job_recovery.comfy_queue_idle(recovery_db.settings) is False


@pytest.mark.parametrize("raw", [b"not json", b"x" * 1_000_001], ids=["malformed", "oversized"])
def test_queue_probe_rejects_malformed_and_oversized_responses(recovery_db, monkeypatch, raw):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.read.return_value = raw
    monkeypatch.setattr(job_recovery.urllib.request, "build_opener", lambda *args: opener)
    assert job_recovery.comfy_queue_idle(recovery_db.settings) is False


@pytest.mark.parametrize("url", ["https://127.0.0.1:8188", "http://example.com:8188", "http://user:pass@localhost:8188"])
def test_queue_probe_rejects_nonlocal_or_credentialed_urls(monkeypatch, url):
    opener = MagicMock(side_effect=AssertionError("No network allowed"))
    monkeypatch.setattr(job_recovery.urllib.request, "build_opener", opener)
    assert job_recovery.comfy_queue_idle(SimpleNamespace(comfyui_base_url=url)) is False
    opener.assert_not_called()


def test_recovery_loop_starts_after_grace_and_stops_cleanly(recovery_db, monkeypatch):
    calls = []
    stop = asyncio.Event()
    def check(*args):
        calls.append(True)
        raise RuntimeError("Transient recovery failure")
    monkeypatch.setattr(job_recovery, "recover_abandoned_local_jobs", check)
    async def exercise():
        task = asyncio.create_task(job_recovery.recovery_loop(
            recovery_db.factory, recovery_db.settings, stop, interval=.01))
        await asyncio.sleep(0)
        assert not calls
        while len(calls) < 2:
            await asyncio.sleep(.005)
        stop.set()
        await asyncio.wait_for(task, timeout=1)
    asyncio.run(asyncio.wait_for(exercise(), timeout=3))
    assert len(calls) >= 2
