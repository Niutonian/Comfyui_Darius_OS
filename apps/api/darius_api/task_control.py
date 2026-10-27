"""Durable user control at assistant execution boundaries."""
from sqlalchemy import select
from .database import Message, Conversation, Job
from .providers import ProviderError


class TaskStopped(ProviderError):
    pass


def check_task_control(bridge):
    if not bridge or not getattr(bridge, "session_factory", None) or not getattr(bridge, "message_id", None):
        return
    with bridge.session_factory() as session:
        message = session.get(Message, bridge.message_id)
        conversation = session.get(Conversation, message.conversation_id) if message else None
        if not message or not conversation or conversation.project_id != bridge.project_id:
            raise ProviderError("Task does not belong to this project")
        action = message.metadata_json.get("task_control")
        if action in {"pause", "cancel"}:
            raise TaskStopped("Task paused. Resume when ready." if action == "pause" else "Task cancelled.")


def recover_interrupted_tasks(session_factory):
    with session_factory.begin() as session:
        for message in session.scalars(select(Message).where(Message.role == "user")):
            metadata = message.metadata_json
            task = metadata.get("task") or {}
            if task.get("state") not in {"running", "pause_requested"}:
                continue
            job = session.get(Job, metadata.get("local_render_job_id")) if metadata.get("local_render_job_id") else None
            state = job.status if job else "paused" if metadata.get("task_control") == "pause" else "interrupted"
            message.metadata_json = {**metadata, "task": {**task, "state": state, "error": "Server restarted. Resume the saved task." if not job else ""}}
