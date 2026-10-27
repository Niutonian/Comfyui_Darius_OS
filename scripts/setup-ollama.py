"""Optional local AI setup. Pull one public model; select it only on request."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'ornith-1.5:9b'
BASE_URL = 'http://127.0.0.1:11434'
DOWNLOAD_BYTES = 6_600_000_000  # Approximate published Q4_K_M model + projector.


class SetupError(RuntimeError):
    pass


class NotRunning(SetupError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Ollama:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def open(self, path, data=None, *, timeout=10):
        request = urllib.request.Request(BASE_URL + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Content-Type': 'application/json'})
        try:
            return self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raise SetupError(f'Ollama returned HTTP {exc.code} during {path}. Check the local Ollama installation and its logs; existing models were kept.') from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ConnectionRefusedError):
                raise NotRunning('Ollama is not listening on 127.0.0.1:11434.') from exc
            raise SetupError('The local Ollama API did not respond. Check its logs and retry.') from exc
        except OSError as exc:
            raise SetupError('The local Ollama API connection failed. Check its logs and retry.') from exc

    def json(self, path, data=None):
        with self.open(path, data) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise SetupError('Ollama returned an oversized metadata response.')
        try:
            result = json.loads(raw)
        except ValueError as exc:
            raise SetupError('The service on port 11434 did not return valid Ollama JSON.') from exc
        if not isinstance(result, dict) or result.get('error'):
            raise SetupError('Ollama returned invalid model metadata. Check its logs and retry.')
        return result

    def probe(self):
        version = self.json('/api/version').get('version')
        if not isinstance(version, str) or not re.match(r'^\d+\.\d+\.\d+', version):
            raise SetupError('Port 11434 does not identify a supported Ollama API. No second server was started.')
        print('Local Ollama API verified.', flush=True)

    def installed(self):
        models = self.json('/api/tags').get('models')
        if not isinstance(models, list) or any(not isinstance(item, dict) or not isinstance(item.get('name') or item.get('model'), str) for item in models):
            raise SetupError('Ollama returned an invalid installed-model list.')
        return any((item.get('name') or item.get('model')) == MODEL for item in models)

    def verify(self):
        if not self.installed():
            raise SetupError('The Ornith download is incomplete. Run the optional setup again to resume it.')
        metadata = self.json('/api/show', {'model': MODEL})
        details = metadata.get('details') or {}
        capabilities = metadata.get('capabilities') or []
        if (not isinstance(details, dict) or details.get('family') != 'qwen35'
                or details.get('parameter_size') not in {'8.95B', '9B', '9.0B'}
                or details.get('quantization_level') != 'Q4_K_M'
                or not isinstance(capabilities, list) or not all(isinstance(c, str) for c in capabilities)
                or not {'completion', 'tools', 'vision'} <= set(capabilities)):
            raise SetupError('This model does not report the expected Ornith 9B Q4_K_M text/tools/vision metadata. Your installed model was preserved. Check the model and Ollama version before selecting it.')
        print('Ornith 1.5 9B verified: Q4_K_M, text, tools and vision. No model inference or GPU load was requested.', flush=True)

    def pull(self):
        if self.installed():
            print('Ornith 1.5 9B is already installed; reusing it.', flush=True)
            self.verify()
            return
        model_root = Path(os.environ.get('OLLAMA_MODELS') or Path.home() / '.ollama' / 'models').expanduser()
        existing = model_root
        while not existing.exists() and existing.parent != existing:
            existing = existing.parent
        if shutil.disk_usage(existing).free < DOWNLOAD_BYTES + 1_000_000_000:
            raise SetupError('Not enough free space at the expected Ollama model location. Allow about 7.6 GB free for this model. If your running daemon uses another model folder, configure OLLAMA_MODELS consistently and retry.')
        print('Downloading ornith-1.5:9b from the public Ollama library (about 6.6 GB). Ollama reuses verified layers and resumes partial downloads.', flush=True)
        success, last_status, last_percent = False, '', -1
        last_print = 0.0
        with self.open('/api/pull', {'model': MODEL, 'stream': True}, timeout=120) as response:
            while True:
                raw = response.readline(65537)
                if not raw:
                    break
                if len(raw) > 65536:
                    raise SetupError('Ollama returned an oversized download event.')
                try:
                    event = json.loads(raw)
                except ValueError as exc:
                    raise SetupError('The model download stream was interrupted. Run setup again to resume.') from exc
                if not isinstance(event, dict) or event.get('error'):
                    raise SetupError('Ollama could not complete the model pull. Check its logs, disk space and Internet access; run setup again to resume. No model was selected.')
                status = event.get('status')
                if not isinstance(status, str):
                    raise SetupError('Ollama returned an invalid download status.')
                total, done = event.get('total'), event.get('completed', 0)
                percent = int(done * 100 / total) if type(total) is int and total > 0 and type(done) is int and 0 <= done <= total else -1
                now = time.monotonic()
                if status != last_status or percent >= last_percent + 2 or now - last_print >= 5:
                    # Report only bounded status text; never raw error bodies or URLs.
                    label = status if re.fullmatch(r'[a-zA-Z0-9 ._:\-]{1,100}', status) else 'Downloading model'
                    print(f'{label}' + (f' - {percent}%' if percent >= 0 else ''), flush=True)
                    last_status, last_percent, last_print = status, percent, now
                if status == 'success':
                    success = True
        if not success:
            raise SetupError('Ollama did not confirm a completed download. Run setup again to resume; your chat provider has not changed.')
        self.verify()


def updated_env(original):
    """Replace only the three explicitly selected provider keys, retaining secrets."""
    bom = original.startswith(b'\xef\xbb\xbf')
    content = original.decode('utf-8-sig')
    newline = '\r\n' if '\r\n' in content else '\n'
    values = {'DARIUS_LLM_PROVIDER': 'ollama', 'OLLAMA_MODEL': MODEL, 'OLLAMA_BASE_URL': BASE_URL}
    seen, lines = set(), []
    for line in content.splitlines(keepends=True):
        match = re.match(r'^\s*(DARIUS_LLM_PROVIDER|OLLAMA_MODEL|OLLAMA_BASE_URL)\s*=', line)
        if match:
            key = match[1]
            lines.append(f'{key}={values[key]}{newline}')
            seen.add(key)
        else:
            lines.append(line)
    result = ''.join(lines)
    if result and not result.endswith(('\r', '\n')):
        result += newline
    for key, value in values.items():
        if key not in seen:
            result += f'{key}={value}{newline}'
    return (b'\xef\xbb\xbf' if bom else b'') + result.encode('utf-8')


def atomic_bytes(path, data):
    temporary = path.with_name('.env.setup-' + uuid4().hex)
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def select_model(settings, root=ROOT):
    """Caller has stopped Darius, verified the model and backed up the installation."""
    from sqlalchemy.engine import make_url
    url = make_url(settings.database_url)
    if url.get_backend_name() != 'sqlite' or not url.database or url.database == ':memory:' or url.query:
        raise SetupError('Automatic chat selection requires a local SQLite installation. Choose Ornith manually in Darius Settings instead.')
    path = root / '.env'
    before = path.read_bytes()
    replacement = updated_env(before)
    database = Path(url.database).resolve()
    changed = False
    from datetime import datetime, timezone
    with sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=5) as connection:
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('''INSERT INTO llm_preferences (id, provider, model, reasoning_effort, updated_at)
                VALUES ('default', 'ollama', ?, 'auto', ?)
                ON CONFLICT(id) DO UPDATE SET provider=excluded.provider, model=excluded.model, updated_at=excluded.updated_at''',
                (MODEL, datetime.now(timezone.utc).isoformat()))
            atomic_bytes(path, replacement)
            changed = True
            connection.commit()
        except Exception:
            connection.rollback()
            if changed:
                atomic_bytes(path, before)
            raise
    print('Ornith 1.5 9B selected for Darius chat. Existing cloud keys and OpenAI thinking preference were retained. Start Darius from the manager.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['probe', 'prepare', 'select'])
    args = parser.parse_args()
    try:
        api = Ollama()
        api.probe()
        if args.action == 'prepare':
            api.pull()
        elif args.action == 'select':
            api.verify()
            sys.path.insert(0, str(ROOT / 'apps/api'))
            from darius_api.config import Settings
            select_model(Settings.from_env())
        return 0
    except NotRunning as exc:
        print(str(exc))
        return 3
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f'Ollama setup could not finish ({type(exc).__name__}). Check the installation and retry. No model inference was requested.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
