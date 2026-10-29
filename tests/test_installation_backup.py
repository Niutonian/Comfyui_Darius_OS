"""Restore synthetic project data without touching live settings or services."""
import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from darius_api.database import Asset, Job, Conversation, Message
from darius_api.installation_backup import backup, restore_rehearsal, checksum
from darius_api.main import create_app
from test_canvas import canvas_client
from test_moss_workspace import add, generate


def seed_workspace(canvas_client, tmp_path):
    client, app, project, launches = canvas_client
    board = add(client, project, 'Backup board')
    receipt = generate(client, project, board)
    image = tmp_path / 'synthetic.png'
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jh1sAAAAASUVORK5CYII='))
    with app.state.session_factory.begin() as session:
        session.add(Conversation(id='backup-chat', project_id=project, title='Garden ideas'))
        session.flush()
        session.add(Message(id='backup-message', conversation_id='backup-chat', role='user', content='Glass flowers'))
        session.add(Asset(id='backup-image', project_id=project, kind='image', role='generation', path=str(image), content_hash=hashlib.sha256(image.read_bytes()).hexdigest(), mime_type='image/png', width=1, height=1, provider='fixture', workflow_run_id=receipt['jobId']))
        job = session.get(Job, receipt['jobId']); job.status='completed'; job.output_asset_ids=['backup-image']
        session.add(Job(id='unfinished-backup-job', project_id=project, provider='local-comfyui', status='queued', input_payload={'worker_ready':True}))
    settings = replace(app.state.settings, repository_root=tmp_path)
    (tmp_path / '.env').write_text('PRIVATE_FIXTURE_SETTING=not-a-real-key\n')
    return settings, project, board, receipt, image


def test_full_backup_restores_board_conversation_asset_and_workflow_receipt(canvas_client, tmp_path):
    settings, project, board, receipt, image = seed_workspace(canvas_client, tmp_path)
    archive = tmp_path / 'private-backup'
    report = backup(archive, settings, include_media=True)
    assert report['assets'][0]['status'] == 'included'
    image.unlink()  # Restored media must not depend on the source file surviving.
    restored = tmp_path / 'restored'
    before = checksum(archive / 'darius.db')
    result = restore_rehearsal(archive, restored)
    assert result['missingAssets'] == [] and result['unfinishedJobsStopped'] == 1
    assert not result['credentialsActivated'] and not (restored / '.env').exists()
    assert (restored / 'settings/backend.env').is_file()
    assert checksum(archive / 'darius.db') == before
    isolated = replace(settings, repository_root=restored, data_dir=restored / 'data', database_url='sqlite:///' + (restored / 'data/darius.db').as_posix(), workflow_definitions_dir=restored / 'workflows/definitions', comfyui_base_url='http://127.0.0.1:1')
    with TestClient(create_app(isolated)) as client:
        assert client.get('/api/v1/conversations/backup-chat/messages').json()[0]['content'] == 'Glass flowers'
        doc = client.get(f"/api/v1/projects/{project}/canvases/{board['documentId']}").json()
        assert doc['generations'][0]['jobId'] == receipt['jobId']
        assert client.get('/api/v1/assets/backup-image/content').content == next((restored / 'data/media').iterdir()).read_bytes()
        assert client.get('/api/v1/jobs/unfinished-backup-job').json()['status'] == 'failed'
    assert (archive / 'BACKUP_REPORT.txt').exists()


def test_default_backup_reports_exclusions_and_never_reads_original_media_after_restore(canvas_client, tmp_path):
    settings, project, board, receipt, image = seed_workspace(canvas_client, tmp_path)
    archive = tmp_path / 'metadata-backup'
    backup(archive, settings)
    restored = tmp_path / 'restored'
    result = restore_rehearsal(archive, restored)
    assert result['missingAssets'][0]['reason'] == 'excluded'
    with sqlite3.connect(restored / 'data/darius.db') as db:
        path = db.execute('SELECT path FROM assets WHERE id=?', ('backup-image',)).fetchone()[0]
        assert Path(path).is_relative_to(restored) and not Path(path).exists()
    assert image.is_file()


def test_restore_rejects_overwrite_tampering_and_unsafe_paths(canvas_client, tmp_path):
    settings, *_ = seed_workspace(canvas_client, tmp_path)
    archive = tmp_path / 'backup'
    backup(archive, settings, include_media=True)
    existing = tmp_path / 'existing'; existing.mkdir(); (existing / 'keep').write_text('keep')
    with pytest.raises(ValueError, match='new folder'): restore_rehearsal(archive, existing)
    assert (existing / 'keep').read_text() == 'keep'
    manifest = json.loads((archive / 'backup-report.json').read_text())
    manifest['files']['../escape'] = '0' * 64
    (archive / 'backup-report.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Unsafe path'): restore_rehearsal(archive, tmp_path / 'unsafe')
    assert not (tmp_path / 'unsafe').exists()
    manifest['files'].pop('../escape'); (archive / 'backup-report.json').write_text(json.dumps(manifest))
    (archive / 'darius.db').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='checksum'): restore_rehearsal(archive, tmp_path / 'tampered')
    with pytest.raises(RuntimeError, match='never overwritten'): backup(archive, settings)
