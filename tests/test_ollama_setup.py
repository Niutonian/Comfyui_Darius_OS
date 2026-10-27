"""Optional local-AI setup never touches real Ollama, models or user settings."""
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import urllib.error

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ollama_setup', ROOT / 'scripts/setup-ollama.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

METADATA = {'details': {'family': 'qwen35', 'parameter_size': '8.95B', 'quantization_level': 'Q4_K_M'},
            'capabilities': ['completion', 'tools', 'vision', 'thinking']}


def fake_api(monkeypatch, *, installed=False, events=None, metadata=None):
    api, calls = setup.Ollama(), []
    state = {'installed': installed}
    def json_api(path, data=None):
        calls.append((path, data))
        if path == '/api/tags':
            return {'models': [{'name': setup.MODEL}] if state['installed'] else []}
        if path == '/api/show':
            return METADATA if metadata is None else metadata
        raise AssertionError(path)
    def open_api(path, data=None, **kwargs):
        assert path == '/api/pull'
        calls.append((path, data))
        state['installed'] = True
        return io.BytesIO(b''.join(json.dumps(item).encode() + b'\n' for item in (events or [{'status': 'success'}])))
    monkeypatch.setattr(api, 'json', json_api)
    monkeypatch.setattr(api, 'open', open_api)
    monkeypatch.setattr(setup.shutil, 'disk_usage', lambda _: SimpleNamespace(free=20_000_000_000))
    return api, calls


def test_installed_model_is_verified_without_pull_or_gpu_request(monkeypatch):
    api, calls = fake_api(monkeypatch, installed=True)
    monkeypatch.setattr(setup.shutil, 'disk_usage', lambda _: pytest.fail('No download-space gate for installed models'))
    api.pull()
    assert all(path in {'/api/tags', '/api/show'} for path, _ in calls)


def test_missing_model_streams_pull_then_verifies_without_inference(monkeypatch):
    api, calls = fake_api(monkeypatch, events=[{'status': 'pulling layers', 'total': 100, 'completed': 50}, {'status': 'success'}])
    api.pull()
    assert ('/api/pull', {'model': setup.MODEL, 'stream': True}) in calls
    assert calls[-1] == ('/api/show', {'model': setup.MODEL})
    assert all(path not in {'/api/chat', '/api/generate'} for path, _ in calls)


def test_insufficient_disk_space_never_starts_pull(monkeypatch):
    api, calls = fake_api(monkeypatch)
    monkeypatch.setattr(setup.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1))
    with pytest.raises(setup.SetupError, match='Not enough free space'):
        api.pull()
    assert calls == [('/api/tags', None)]


@pytest.mark.parametrize('events', [[{'status': 'pulling'}], [{'error': 'private-error-body'}], [{'status': None}]])
def test_interrupted_or_rejected_download_is_not_success(monkeypatch, events):
    api, _ = fake_api(monkeypatch, events=events)
    with pytest.raises(setup.SetupError) as error:
        api.pull()
    assert 'private-error-body' not in str(error.value)


@pytest.mark.parametrize('metadata', [{}, {'details': METADATA['details'], 'capabilities': ['completion']},
    {'details': {**METADATA['details'], 'parameter_size': '35B'}, 'capabilities': METADATA['capabilities']},
    {'details': {**METADATA['details'], 'quantization_level': 'Q8_0'}, 'capabilities': METADATA['capabilities']}])
def test_customized_or_incompatible_tag_is_preserved_not_pulled_over(monkeypatch, metadata):
    api, calls = fake_api(monkeypatch, installed=True, metadata=metadata)
    with pytest.raises(setup.SetupError, match='installed model was preserved'):
        api.pull()
    assert not any(path == '/api/pull' for path, _ in calls)


def test_only_connection_refusal_means_not_running(monkeypatch):
    api = setup.Ollama()
    def fail(error):
        class Opener:
            def open(self, *args, **kwargs): raise error
        monkeypatch.setattr(api, 'opener', Opener())
    fail(urllib.error.URLError(ConnectionRefusedError()))
    with pytest.raises(setup.NotRunning): api.probe()
    fail(urllib.error.URLError(TimeoutError()))
    with pytest.raises(setup.SetupError) as error: api.probe()
    assert not isinstance(error.value, setup.NotRunning)
    fail(urllib.error.HTTPError(setup.BASE_URL, 404, 'private-body', {}, None))
    with pytest.raises(setup.SetupError, match='HTTP 404') as error: api.probe()
    assert 'private-body' not in str(error.value)


def test_redirects_are_never_followed():
    assert setup.NoRedirect().redirect_request(None, None, None, None, None, None) is None


@pytest.mark.parametrize('original', [
    b'# retain comments\r\nOPENAI_API_KEY=private\r\nDARIUS_LLM_PROVIDER=openai\r\nOLLAMA_MODEL=old\r\n',
    b'\xef\xbb\xbfHF_TOKEN=private\nDARIUS_LLM_PROVIDER="deepseek"\nDARIUS_LLM_PROVIDER=opencode\nKEEP=true',
])
def test_provider_environment_edit_preserves_keys_comments_and_bom(original):
    result = setup.updated_env(original)
    assert (result.startswith(b'\xef\xbb\xbf')) == (original.startswith(b'\xef\xbb\xbf'))
    for line in original.decode('utf-8-sig').splitlines():
        if not line.startswith(('DARIUS_LLM_PROVIDER=', 'OLLAMA_MODEL=', 'OLLAMA_BASE_URL=')):
            assert line.encode() in result
    text = result.decode('utf-8-sig')
    assert 'DARIUS_LLM_PROVIDER=openai' not in text
    assert f'OLLAMA_MODEL={setup.MODEL}' in text
    assert f'OLLAMA_BASE_URL={setup.BASE_URL}' in text
    assert 'DARIUS_LLM_PROVIDER=ollama' in text


@pytest.fixture
def selection(tmp_path):
    database = tmp_path / 'custom.db'
    with sqlite3.connect(database) as conn:
        conn.execute('''CREATE TABLE llm_preferences (id TEXT PRIMARY KEY, provider TEXT, model TEXT,
            reasoning_effort TEXT, updated_at TEXT)''')
        conn.execute("INSERT INTO llm_preferences VALUES ('default', 'openai', 'chosen-model', 'high', 'old')")
    env = b'OPENAI_API_KEY=private\nHF_TOKEN=private\nDARIUS_LLM_PROVIDER=openai\nOLLAMA_MODEL=old\n'
    (tmp_path / '.env').write_bytes(env)
    return tmp_path, database, env, SimpleNamespace(database_url=f'sqlite:///{database.as_posix()}')


def test_explicit_selection_updates_saved_choice_and_preserves_openai_preferences(selection):
    root, database, original, settings = selection
    setup.select_model(settings, root)
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT provider, model, reasoning_effort FROM llm_preferences').fetchone() == ('ollama', setup.MODEL, 'high')
    assert b'OPENAI_API_KEY=private\nHF_TOKEN=private\n' in (root / '.env').read_bytes()
    assert (root / '.env').read_bytes() != original


def test_env_write_failure_rolls_back_database_selection(selection, monkeypatch):
    root, database, original, settings = selection
    monkeypatch.setattr(setup, 'atomic_bytes', lambda *args: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(PermissionError): setup.select_model(settings, root)
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT provider FROM llm_preferences').fetchone() == ('openai',)
    assert (root / '.env').read_bytes() == original


def test_commit_failure_restores_environment_and_previous_selection(selection, monkeypatch):
    root, database, original, settings = selection
    real_connect = sqlite3.connect
    class FailingCommit:
        def __init__(self, connection): self.connection = connection
        def __enter__(self): return self
        def __exit__(self, *args): self.connection.close()
        def execute(self, *args): return self.connection.execute(*args)
        def rollback(self): self.connection.rollback()
        def commit(self): raise sqlite3.OperationalError('simulated commit failure')
    monkeypatch.setattr(setup.sqlite3, 'connect', lambda *args, **kwargs: FailingCommit(real_connect(*args, **kwargs)))
    with pytest.raises(sqlite3.OperationalError): setup.select_model(settings, root)
    assert (root / '.env').read_bytes() == original
    with real_connect(database) as conn:
        assert conn.execute('SELECT provider FROM llm_preferences').fetchone() == ('openai',)


def test_external_or_missing_database_is_not_created_or_selected(selection):
    root, database, original, _ = selection
    with pytest.raises(setup.SetupError, match='SQLite'):
        setup.select_model(SimpleNamespace(database_url='postgresql://localhost/darius'), root)
    absent = root / 'missing.db'
    with pytest.raises(sqlite3.Error):
        setup.select_model(SimpleNamespace(database_url=f'sqlite:///{absent.as_posix()}'), root)
    assert not absent.exists()
    assert (root / '.env').read_bytes() == original


def test_real_http_stream_metadata_and_pull_flow_is_readiness_only(monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    state = {'installed': False, 'paths': []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self): self.reply()
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert payload['model'] == setup.MODEL
            self.reply()
        def reply(self):
            state['paths'].append(self.path)
            if self.path == '/api/version': body = {'version': '0.18.2'}
            elif self.path == '/api/tags': body = {'models': [{'name': setup.MODEL}] if state['installed'] else []}
            elif self.path == '/api/show': body = METADATA
            elif self.path == '/api/pull': state['installed'] = True; body = {'status': 'success'}
            else: raise AssertionError(self.path)
            self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(body).encode() + b'\n')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        monkeypatch.setattr(setup, 'BASE_URL', f'http://127.0.0.1:{server.server_port}')
        monkeypatch.setattr(setup.shutil, 'disk_usage', lambda _: SimpleNamespace(free=20_000_000_000))
        api = setup.Ollama(); api.probe(); api.pull(); api.pull()
        assert state['paths'].count('/api/pull') == 1
        assert '/api/chat' not in state['paths'] and '/api/generate' not in state['paths']
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
