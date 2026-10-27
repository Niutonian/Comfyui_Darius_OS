from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from darius_api.main import create_app
from darius_api.database import Job, ProjectEvent
from test_media_backend import settings_for, create_project
from test_assistant import FakeAssistant


def message(client, project):
    cid=client.post(f'/api/v1/projects/{project}/conversations',json={}).json()['id']
    return client.post(f'/api/v1/conversations/{cid}/messages',json={'role':'assistant','content':'An orange-uniformed alien postal worker.\n\nKeep the city rainy.'}).json()


def idea(source, **patch):
    return {'id':str(uuid4()),'title':'Alien postal worker','content':'An alien mail service in a rainy city.',
            'sourceMessageId':source['id'],'sourceText':source['content'],**patch}


def test_explicit_save_is_durable_idempotent_and_creates_no_jobs(tmp_path):
    settings=settings_for(tmp_path);provider=FakeAssistant();app=create_app(settings,planner_provider=provider)
    with TestClient(app) as client:
        project=create_project(client);source=message(client,project);body=idea(source);url=f'/api/v1/projects/{project}/ideas'
        saved=client.post(url,json=body);assert saved.status_code==200,saved.text
        assert client.post(url,json=body).json()['revision']==saved.json()['revision']
        assert client.post(url,json={**body,'content':'Changed retry'}).status_code==409
        assert client.get(url).json()[0]['content']==body['content']
        assert not provider.calls
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Job))==0
            assert session.scalar(select(func.count()).select_from(ProjectEvent).where(ProjectEvent.event_type=='idea.saved'))==1
    with TestClient(create_app(settings,planner_provider=provider)) as reopened:
        assert reopened.get(url).json()[0]['title']==body['title']


def test_ideas_are_project_scoped_and_require_a_real_source(tmp_path):
    app=create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        a,b=create_project(client),create_project(client,'Other')
        source=message(client,a);url=f'/api/v1/projects/{a}/ideas';body=idea(source)
        saved=client.post(url,json=body).json()
        assert client.get(f'/api/v1/projects/{b}/ideas').json()==[]
        assert client.post(f'/api/v1/projects/{b}/ideas',json=idea(source)).status_code==422
        assert client.post(url,json=idea(source,sourceText='Unrelated text')).status_code==422
        assert client.post(url,json=idea(source,sourceMessageId='missing')).status_code==422
        assert client.post(f'/api/v1/projects/{b}/ideas/{saved["id"]}/state',json={'revision':saved['revision'],'archived':True}).status_code==404
        assert client.post(url,json=idea(source,title=' ')).status_code==422


def test_archive_restore_conflicts_and_saved_idea_context(tmp_path):
    provider=FakeAssistant();app=create_app(settings_for(tmp_path),planner_provider=provider)
    with TestClient(app) as client:
        project=create_project(client);source=message(client,project);url=f'/api/v1/projects/{project}/ideas'
        saved=client.post(url,json=idea(source)).json();state=url+'/'+saved['id']+'/state'
        archived=client.post(state,json={'revision':saved['revision'],'archived':True}).json()
        assert client.get(url).json()==[]
        assert client.get(url+'?archived=true').json()[0]['id']==saved['id']
        assert client.post(state,json={'revision':saved['revision'],'archived':True}).json()['revision']==archived['revision']
        assert client.post(state,json={'revision':saved['revision'],'archived':False}).status_code==409
        assert client.post(state,json={'revision':archived['revision'],'archived':False}).status_code==200
        # A later discussion receives explicitly saved concepts as read-only context.
        cid=source['conversation_id']
        user=client.post(f'/api/v1/conversations/{cid}/messages',json={'role':'user','content':'What was our idea?'}).json()
        assert client.post(f'/api/v1/conversations/{cid}/reply',json={'message_id':user['id']}).status_code==200
        assert provider.calls[-1][0]['saved_ideas'][0]['title']=='Alien postal worker'
        assert client.get(f'/api/v1/jobs?project_id={project}').json()==[]
