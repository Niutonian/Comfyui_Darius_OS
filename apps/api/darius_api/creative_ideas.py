"""Explicitly saved project ideas, persisted in the existing project event ledger."""
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import func, select, text

from .canvas_document import StrictModel
from .database import Conversation, Message, Project, ProjectEvent
from .services import add_event


class SaveIdea(StrictModel):
    id: UUID
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=30000)
    sourceMessageId: str = Field(min_length=1, max_length=36)
    sourceText: str = Field(min_length=1, max_length=30000)


class IdeaState(StrictModel):
    revision: str = Field(min_length=1, max_length=36)
    archived: bool


def latest_ideas(session, project_id, *, archived=False, limit=200):
    ranked = select(ProjectEvent.id.label('id'), func.row_number().over(
        partition_by=ProjectEvent.entity_id, order_by=(ProjectEvent.created_at.desc(), ProjectEvent.id.desc())).label('position')).where(
            ProjectEvent.project_id == project_id, ProjectEvent.entity_type == 'idea',
            ProjectEvent.event_type.in_(['idea.saved', 'idea.state_changed'])).subquery()
    rows = session.scalars(select(ProjectEvent).join(ranked, ProjectEvent.id == ranked.c.id).where(
        ranked.c.position == 1, ProjectEvent.payload['archived'].as_boolean() == archived).order_by(ProjectEvent.created_at.desc()).limit(limit))
    return [idea_view(row) for row in rows]


def idea_view(row):
    return {"id":row.entity_id, "projectId":row.project_id, "revision":row.id,
            "updatedAt":row.created_at.isoformat(), **row.payload}


def router(session_factory):
    routes = APIRouter(prefix='/api/v1/projects/{project_id}/ideas', tags=['creative-ideas'])

    def owned(session, project_id):
        if not session.get(Project, project_id): raise HTTPException(404, 'Project does not exist')

    @routes.get('')
    def listing(project_id: str, archived: bool = False):
        with session_factory() as session:
            owned(session, project_id)
            return latest_ideas(session, project_id, archived=archived)

    @routes.post('')
    def save(project_id: str, payload: SaveIdea):
        with session_factory.begin() as session:
            session.execute(text('BEGIN IMMEDIATE'))
            owned(session, project_id)
            existing = session.get(ProjectEvent, str(payload.id))
            if existing:
                if existing.project_id != project_id or existing.event_type != 'idea.saved' or any(
                    existing.payload.get(key) != getattr(payload, key) for key in ('title','content','sourceMessageId','sourceText')):
                    raise HTTPException(409, 'This save identity belongs to another idea')
                return idea_view(existing)
            source = session.get(Message, payload.sourceMessageId)
            conversation = session.get(Conversation, source.conversation_id) if source else None
            if not source or source.role not in {'user','assistant'} or not conversation or conversation.project_id != project_id:
                raise HTTPException(422, "Choose text from this project's conversation")
            if payload.sourceText not in source.content:
                raise HTTPException(422, 'The selected text is not part of this message')
            if not payload.title.strip() or not payload.content.strip():
                raise HTTPException(422, 'Give the idea a title and some text')
            row = ProjectEvent(id=str(payload.id), project_id=project_id, event_type='idea.saved', entity_type='idea', entity_id=str(payload.id),
                payload={'title':payload.title, 'content':payload.content, 'sourceMessageId':source.id,
                         'sourceText':payload.sourceText, 'conversationId':source.conversation_id, 'archived':False})
            session.add(row); session.flush()
            return idea_view(row)

    @routes.post('/{idea_id}/state')
    def state(project_id: str, idea_id: str, payload: IdeaState):
        with session_factory.begin() as session:
            session.execute(text('BEGIN IMMEDIATE'))
            owned(session, project_id)
            row = session.scalar(select(ProjectEvent).where(ProjectEvent.project_id == project_id,
                ProjectEvent.entity_type == 'idea', ProjectEvent.entity_id == idea_id,
                ProjectEvent.event_type.in_(['idea.saved','idea.state_changed'])).order_by(ProjectEvent.created_at.desc(), ProjectEvent.id.desc()).limit(1))
            if not row: raise HTTPException(404, 'Idea does not belong to this project')
            if row.payload['archived'] == payload.archived: return idea_view(row)
            if row.id != payload.revision: raise HTTPException(409, 'This idea changed on another device. Refresh before changing it.')
            event = add_event(session, project_id, 'idea.state_changed', 'idea', idea_id, {**row.payload,'archived':payload.archived})
            session.flush()
            return idea_view(event)

    return routes
