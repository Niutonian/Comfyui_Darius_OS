"""Private workspace backup and offline restore rehearsal. No services are started."""
from __future__ import annotations
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4


def checksum(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): result.update(block)
    return result.hexdigest()


def backup(destination: Path, settings, *, include_media=False):
    from sqlalchemy.engine import make_url
    url = make_url(settings.database_url)
    if url.get_backend_name() != 'sqlite' or url.query:
        raise RuntimeError('Automatic recovery supports ordinary SQLite files only; back up an external database manually.')
    destination = Path(destination).resolve()
    if destination.is_relative_to(settings.workflow_definitions_dir.resolve()): raise ValueError("Choose a backup folder outside workflow definitions.")
    destination.mkdir(parents=True, exist_ok=True)
    if any((destination / name).exists() for name in ('darius.db', 'backup-report.json')):
        raise RuntimeError('This backup already contains recovery data. Choose a new folder; existing backups are never overwritten.')
    files = {}; assets = []; workflows = []; external_workflows = []
    definitions = settings.workflow_definitions_dir.resolve()
    def store(source, relative):
        source = Path(source)
        if source.is_symlink(): raise ValueError('Backup does not follow file links.')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        before = checksum(source)
        if target.exists():
            if checksum(target) != before: raise ValueError('Backup destination contains a conflicting file.')
        else: shutil.copy2(source, target)
        if checksum(source) != before or checksum(target) != before: raise ValueError('A file changed during backup. Stop Darius and retry into a new folder.')
        files[relative] = before
        return relative
    for source, name in ((settings.repository_root / '.env', 'backend.env'), (settings.repository_root / 'apps/web/.env.local', 'frontend.env')):
        if source.is_file(): store(source, name)
    source_db = Path(url.database).resolve() if url.database and url.database != ':memory:' else None
    if source_db and source_db.is_file():
        temp = destination / (uuid4().hex + '.partial')
        with closing(sqlite3.connect(source_db.as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(temp)) as saved, saved:
                source.backup(saved)
                if saved.execute('PRAGMA integrity_check').fetchone() != ('ok',): raise RuntimeError('Database backup integrity check failed.')
        temp.rename(destination / 'darius.db')
        files['darius.db'] = checksum(destination / 'darius.db')
        with closing(sqlite3.connect(destination / 'darius.db')) as saved:
            saved.row_factory = sqlite3.Row
            tables = {row[0] for row in saved.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'workflow_definitions' in tables:
                for key, payload in saved.execute('SELECT id, contract FROM workflow_definitions'):
                    value = json.loads(payload); reference = Path(value.get('workflow_reference', ''))
                    if reference.is_absolute() and not reference.resolve().is_relative_to(definitions):
                        external_workflows.append({'id': key, 'path': str(reference), 'exists': reference.is_file()})
            if 'assets' in tables:
                for row in saved.execute('SELECT id, path, content_hash FROM assets'):
                    path = Path(row['path'])
                    item = {'id': row['id'], 'originalPath': str(path), 'storedPath': None, 'status': 'excluded'}
                    if not path.is_file(): item['status'] = 'missing'
                    elif include_media:
                        suffix = path.suffix if path.suffix[1:].isalnum() and len(path.suffix) < 12 else '.bin'
                        relative = 'media/' + hashlib.sha256(row['id'].encode()).hexdigest() + suffix
                        store(path, relative)
                        if row['content_hash'] and files[relative] != row['content_hash']: raise ValueError('An asset no longer matches its recorded content version; backup stopped.')
                        item.update(storedPath=relative, status='included')
                    assets.append(item)
    definitions = settings.workflow_definitions_dir.resolve()
    if definitions.exists():
        for source in sorted(definitions.rglob('*.json')):
            if source.is_symlink() or not source.resolve().is_relative_to(definitions): raise ValueError('Workflow source escapes its definitions folder.')
            relative = 'workflows/definitions/' + source.relative_to(definitions).as_posix()
            store(source, relative); workflows.append({'originalPath': str(source.resolve()), 'storedPath': relative})
    report = {'schemaVersion': 1, 'private': True, 'databaseIncluded': 'darius.db' in files,
        'mediaIncluded': include_media, 'assets': assets, 'workflows': workflows, 'files': files, 'externalWorkflowReferences': external_workflows,
        'externalDependencies': ['Matching Darius release and bundled workflow templates', 'Imported Block Party ZIP originals and model-access approvals', 'ComfyUI installation, custom nodes and model weights', 'Voice runtimes and local chat models', 'FFmpeg, GPU drivers and LAN certificates'],
        'pendingJobsPolicy': 'Restore marks unfinished jobs failed for explicit review; no worker or service is started.'}
    (destination / 'backup-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    counts = {state: sum(item['status'] == state for item in assets) for state in ('included', 'excluded', 'missing')}
    summary = f"Private recovery backup. Do not share.\nDatabase included: {report['databaseIncluded']}\nAssets included: {counts['included']}; excluded: {counts['excluded']}; missing: {counts['missing']}\nWorkflow files included: {len(workflows)}; external workflow references: {len(external_workflows)}\nSettings may contain API keys. Models, ComfyUI and voice runtimes are not included.\nRestore into a NEW folder using the manager's Restore rehearsal action.\n"
    (destination / 'BACKUP_REPORT.txt').write_text(summary, encoding='utf-8')
    return report


def restore_rehearsal(source: Path, destination: Path):
    source = Path(source).resolve(); destination = Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source): raise ValueError('Restore requires a new folder outside the backup. Nothing was overwritten.')
    manifest = source / 'backup-report.json'
    if not manifest.is_file(): raise ValueError('Select a completed backup containing backup-report.json; a settings-only backup cannot restore the workspace.')
    if manifest.stat().st_size > 8 * 1024 * 1024: raise ValueError('Backup report exceeds the supported size.')
    report = json.loads(manifest.read_text(encoding='utf-8'))
    if report.get('schemaVersion') != 1 or not report.get('databaseIncluded'): raise ValueError('This backup has no supported database recovery report.')
    verified = {}
    for name, expected in report['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or ':' in name or '\\' in name: raise ValueError('Unsafe path in backup report.')
        origin = (source / name).resolve()
        if not origin.is_relative_to(source) or not origin.is_file() or checksum(origin) != expected: raise ValueError('Backup is missing or a checksum changed. Original backup remains untouched.')
        verified[name] = origin
    if 'darius.db' not in verified: raise ValueError('Missing verified database.')
    # Validate every asset/workflow mapping BEFORE creating the destination.
    for item in [*report['assets'], *report['workflows']]:
        if item.get('storedPath') and item['storedPath'] not in verified: raise ValueError('Unverified file mapping in backup.')
    destination.mkdir(parents=True)
    for name, origin in verified.items():
        target_name = 'data/darius.db' if name == 'darius.db' else 'settings/' + name if name in ('backend.env', 'frontend.env') else 'data/' + name if name.startswith('media/') else name
        target = destination / target_name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(origin, target)
    workflow_paths = {item['originalPath']: str(destination / item['storedPath']) for item in report['workflows']}
    unavailable = []
    def rebase_contract(value, original_path=None):
        reference = value.get('workflow_reference')
        if not isinstance(reference, str): return False
        resolved = str((Path(original_path).parent / reference).resolve()) if original_path and not Path(reference).is_absolute() else reference
        target = workflow_paths.get(reference) or workflow_paths.get(resolved)
        if target:
            value['workflow_reference'] = target
        else:
            unavailable.append(value.get('id', 'unknown'))
            value['enabled'] = False
            value['workflow_reference'] = str(destination / 'workflows/unavailable' / (hashlib.sha256(reference.encode()).hexdigest() + '.json'))
        return True
    for item in report['workflows']:
        path = destination / item['storedPath']; value = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(value, dict) and rebase_contract(value, item['originalPath']):
            path.write_text(json.dumps(value, indent=2), encoding='utf-8')
    missing = []; stopped = 0
    with closing(sqlite3.connect(destination / 'data/darius.db')) as database, database:
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'assets' in tables:
            for item in report['assets']:
                target = destination / 'data' / item['storedPath'] if item['storedPath'] else destination / 'data' / 'missing-assets' / hashlib.sha256(item['id'].encode()).hexdigest()
                if not item['storedPath']: missing.append({'id': item['id'], 'originalPath': item['originalPath'], 'reason': item['status']})
                database.execute('UPDATE assets SET path=? WHERE id=?', (str(target), item['id']))
        if 'workflow_definitions' in tables:
            for key, payload in database.execute('SELECT id, contract FROM workflow_definitions').fetchall():
                value = json.loads(payload)
                if rebase_contract(value):
                    database.execute('UPDATE workflow_definitions SET contract=?, enabled=? WHERE id=?', (json.dumps(value), int(value.get('enabled', True)), key))
        if 'jobs' in tables:
            stopped = database.execute("UPDATE jobs SET status='failed', status_message='Restored unfinished task; review before retrying', error_code='RestoreReviewRequired', error_detail='Restore rehearsal never replays unfinished work.' WHERE status IN ('queued','running','cancelling')").rowcount
        if database.execute('PRAGMA integrity_check').fetchone() != ('ok',): raise RuntimeError('Restored database integrity check failed.')
    result = {'unavailableWorkflowIds': sorted(set(unavailable)), 'externalWorkflowReferences': report.get('externalWorkflowReferences', []), 'missingAssets': missing, 'unfinishedJobsStopped': stopped, 'credentialsActivated': False, 'servicesStarted': False, 'externalDependencies': report['externalDependencies']}
    (destination / 'restore-report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (destination / 'RESTORE_REPORT.txt').write_text(f"OFFLINE RESTORE REHEARSAL\nMissing/excluded assets: {len(missing)}\nUnfinished jobs stopped for review: {stopped}\nUnavailable workflow definitions: {len(set(unavailable))}\nCredentials are under settings/ and are NOT activated. No service was started.\nUse a fresh Darius installation and explicitly configure its restored database/media/workflow folders before testing. Never point it at the original database.\n", encoding='utf-8')
    return result
