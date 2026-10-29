"""Catalog refresh must not contend with workers for unchanged workflow rows."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
import sqlite3

from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from darius_api.database import Base, WorkflowDefinitionRecord, make_engine, make_session_factory
from darius_api.services import register_workflows
from darius_api.workflows import RuntimeMapping, WorkflowContract, WorkflowOutput, WorkflowRegistry
from test_canvas import canvas_client


def registry_for(tmp_path):
    definitions = tmp_path / 'definitions'
    definitions.mkdir(exist_ok=True)
    graph = tmp_path / 'graph.json'
    graph.write_text('{}', encoding='utf-8')
    contract = WorkflowContract(
        id='example', name='Example', version='1', capability='text-to-image',
        execution_provider='local-comfyui', workflow_reference=str(graph),
        required_inputs=[], output=WorkflowOutput(kind='image'),
        runtime_mapping=RuntimeMapping(filename_prefix_slot='output.filename_prefix'),
    )
    (definitions / 'example.json').write_text(contract.model_dump_json(), encoding='utf-8')
    registry = WorkflowRegistry(definitions)
    registry.load()
    return registry, contract


def test_unchanged_catalog_is_read_only_even_while_worker_holds_writer(tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path / "queue.db"}')
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    registry, _ = registry_for(tmp_path)
    register_workflows(factory, registry)
    with factory() as session:
        timestamp = session.get(WorkflowDefinitionRecord, 'example').updated_at
    statements = []
    event.listen(engine, 'before_cursor_execute', lambda c, cursor, sql, *args: statements.append(sql))
    # An unchanged catalog must not need a write lock at all. Keep a short timeout
    # so a regression fails promptly, rather than waiting for the production limit.
    event.listen(engine, 'connect', lambda c, _: c.execute('PRAGMA busy_timeout=80'))
    try:
        with engine.connect() as writer:
            writer.exec_driver_sql('BEGIN IMMEDIATE')
            register_workflows(factory, registry)
            writer.rollback()
        assert not any(sql.lstrip().upper().startswith(('UPDATE ', 'INSERT ')) for sql in statements)
        with factory() as session:
            assert session.get(WorkflowDefinitionRecord, 'example').updated_at == timestamp
    finally:
        engine.dispose()


def test_queue_registration_only_touches_its_new_contract(tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path / "queue.db"}')
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    registry, contract = registry_for(tmp_path)
    register_workflows(factory, registry)
    registry.add(contract.model_copy(update={'id': 'new-board', 'name': 'New board'}))
    changed = contract.model_copy(update={'name': 'Unrelated catalog update'})
    (registry.definitions_dir / 'example.json').write_text(changed.model_dump_json(), encoding='utf-8')
    registry.load()
    try:
        register_workflows(factory, registry, workflow_ids=['new-board'])
        with factory() as session:
            assert session.get(WorkflowDefinitionRecord, 'new-board').name == 'New board'
            assert session.get(WorkflowDefinitionRecord, 'example').name == 'Example'
        register_workflows(factory, registry)
        with factory() as session:
            assert session.get(WorkflowDefinitionRecord, 'example').name == 'Unrelated catalog update'
    finally:
        engine.dispose()


def test_api_and_worker_can_register_overlapping_catalogs(tmp_path):
    url = f'sqlite:///{tmp_path / "queue.db"}'
    engines = [make_engine(url), make_engine(url)]
    Base.metadata.create_all(engines[0])
    registry, contract = registry_for(tmp_path)
    for i in range(10):
        registry.add(contract.model_copy(update={'id': f'board-{i}'}))
    barrier = Barrier(2)

    def register(engine):
        barrier.wait(timeout=5)
        register_workflows(make_session_factory(engine), registry)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(register, engines))
        with make_session_factory(engines[0])() as session:
            assert len(session.scalars(select(WorkflowDefinitionRecord)).all()) == 11
        with engines[0].connect() as connection:
            assert connection.exec_driver_sql('PRAGMA busy_timeout').scalar() >= 30000
    finally:
        for engine in engines:
            engine.dispose()


def test_parallel_board_queue_requests_retain_distinct_idempotent_jobs(canvas_client, monkeypatch):
    from darius_api import canvas_images as images
    from test_moss_workspace import add

    client, app, project, launches = canvas_client
    monkeypatch.setattr(images, 'readiness', lambda *args, **kwargs: {'ready': True, 'issues': []})
    config = images.Config(activeProfile=images.FLUX)
    config.drafts[images.FLUX].prompt = 'A blue ceramic owl'
    config.drafts[images.FLUX].enhance = False
    boards = [add(client, project), add(client, project, settings={'adapterVersion': images.FLUX, 'image': config.model_dump()})]
    path = f'/api/v1/projects/{project}/canvases/{boards[0]["documentId"]}'
    doc = client.get(path).json()
    saved = client.post(path + '/save', json={'revision': doc['revision'], 'content': {**doc['content'], 'globalPrompt': 'A red cube'}})
    assert saved.status_code == 200, saved.text
    payloads = [{'revision': 1, 'boardRevision': 1, 'boardId': b['id'], 'profileId': b['settings']['adapterVersion'],
                 'idempotencyKey': f'parallel-board-{i}', 'seed': 42, 'approved': True} for i, b in enumerate(boards)]
    payloads[0]['revision'] = saved.json()['revision']

    def queue(i):
        response = client.post(f'/api/v1/projects/{project}/canvases/{boards[i]["documentId"]}/generate', json=deepcopy(payloads[i]))
        assert response.status_code == 200, response.text
        return response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(queue, range(2)))
    assert len({r['jobId'] for r in receipts}) == 2
    assert len(launches) == 2
    for i in range(2):
        assert queue(i)['jobId'] == receipts[i]['jobId']
    assert len(launches) == 2


def test_busy_queue_response_retains_request_and_uses_existing_job_on_retry(canvas_client, monkeypatch):
    from darius_api import canvas_api
    from test_moss_workspace import add

    client, app, project, launches = canvas_client
    board = add(client, project)
    path = f'/api/v1/projects/{project}/canvases/{board["documentId"]}'
    doc = client.get(path).json()
    saved = client.post(path + '/save', json={'revision': doc['revision'], 'content': {**doc['content'], 'globalPrompt': 'A red cube'}}).json()
    payload = {'revision': saved['revision'], 'boardRevision': 1, 'boardId': board['id'],
               'idempotencyKey': 'retry-storage-busy', 'seed': 42, 'approved': True}
    original = canvas_api.register_workflows

    def busy(*args, **kwargs):
        raise OperationalError('UPDATE', {}, sqlite3.OperationalError('database is locked'))

    monkeypatch.setattr(canvas_api, 'register_workflows', busy)
    response = client.post(path + '/generate', json=payload)
    assert response.status_code == 503
    assert response.headers['Retry-After'] == '1'
    assert 'retry this saved request' in response.json()['detail']
    assert not launches
    monkeypatch.setattr(canvas_api, 'register_workflows', original)
    response = client.post(path + '/generate', json=payload)
    assert response.status_code == 200, response.text
    repeated = client.post(path + '/generate', json=payload)
    assert repeated.status_code == 200 and repeated.json()['jobId'] == response.json()['jobId']
    assert len(launches) == 1
