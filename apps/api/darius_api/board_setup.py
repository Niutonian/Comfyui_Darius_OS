"""First-use Canvas preparation. Block Party provisions; Darius alone renders."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
from hashlib import sha256
import importlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request
from uuid import uuid4
from urllib.parse import urlparse

from .atomic_files import atomic_json
from .block_party_readiness import comfy_root
from .canvas_moss import digest

BLOCK_PARTY_COMMIT = 'dfabe49c77ae4dbffb65045c8ec61abe4453bb9c'
BLOCK_PARTY_REPOSITORY = 'https://github.com/Niutonian/Comfyui_BlockParty.git'
_guard = threading.RLock()
_host_lock = threading.Lock()
_active: set[tuple[str, str]] = set()
_preparing: set[tuple[str, str]] = set()
_log = logging.getLogger(__name__)


@contextmanager
def _private_home(settings):
    previous = os.environ.get('ONE_JOB_HOME')
    os.environ['ONE_JOB_HOME'] = str(settings.data_dir / 'board-setup' / 'block-party-home')
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop('ONE_JOB_HOME', None)
        else:
            os.environ['ONE_JOB_HOME'] = previous


class SetupError(ValueError):
    pass


def profile_graph(settings, profile):
    from . import canvas_fibo as fibo, canvas_h3 as h3, canvas_images as images, canvas_moss as moss
    if profile == moss.VERSION:
        return moss.template(settings)
    if profile in fibo.PROFILES:
        return fibo.artifacts(settings, profile)[1]
    if profile in images.PROFILES:
        return images.artifacts(settings, profile)[0]
    if profile in h3.PROFILES:
        return h3.artifacts(settings, profile)[0]
    raise SetupError('Unknown board recipe.')


def package(settings, profile):
    graph = profile_graph(settings, profile)
    path = settings.repository_root / 'workflows' / 'board-setup' / (profile + '.json')
    try:
        spec = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise SetupError('This board has no published dependency package yet. Export its Block Party setup recipe before distributing it.') from error
    if spec.get('profile') != profile or spec.get('graphDigest') != digest(graph):
        raise SetupError('The board dependency package no longer matches its pinned workflow. Re-export this recipe; no dependencies were changed.')
    return spec, graph


def _context(settings):
    # A preparation result belongs to this machine's selected host and package.
    from .comfy_connection import effective_settings
    settings = effective_settings(settings)
    root = comfy_root(settings)
    return sha256(str((root, settings.comfyui_base_url)).encode()).hexdigest()[:20]


def _key(settings, profile):
    return str(settings.data_dir.resolve()), profile


def _directory(settings, profile):
    profile_graph(settings, profile)  # Never turn a supplied string into a path first.
    return settings.data_dir / 'board-setup' / _context(settings) / profile


def _write(settings, profile, **values):
    path = _directory(settings, profile) / 'status.json'
    atomic_json(path, {**values, 'profile': profile, 'updatedAt': datetime.now(timezone.utc).isoformat()})


def status(settings, profile):
    spec, _ = package(settings, profile)
    try:
        value = json.loads((_directory(settings, profile) / 'status.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        value = {'state': 'unchecked', 'profile': profile}
    if value.get('packageDigest') != digest(spec):
        return {'state': 'unchecked', 'profile': profile}
    if value.get('state') == 'ready' and value.get('reusedNodes'):
        from .board_node_reuse import receipt_matches
        if not receipt_matches(comfy_root(settings), value['reusedNodes']):
            return {'state': 'unchecked', 'profile': profile,
                    'message': 'An installed node revision changed. Check dependencies again.'}
    with _guard:
        if value.get('state') in {'checking', 'preparing'} and _key(settings, profile) not in _active:
            value.update(state='interrupted', message='Preparation was interrupted. Check again to resume verified downloads.')
    # Plans contain local destination paths and never leave the backend.
    return {key: val for key, val in value.items() if key != 'privatePlan'}


def _git(root, *args, timeout=180):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True,
        timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise SetupError('Block Party setup could not complete its Git operation. Check Git, Internet access and write permissions; no existing node pack was replaced.')
    return result.stdout.strip()


def runtime(settings, notify):
    root = settings.data_dir / 'tools' / 'block-party' / BLOCK_PARTY_COMMIT
    if not (root / '.git').is_dir():
        if root.exists():
            raise SetupError('An incomplete Block Party tool folder exists. Keep it for inspection and repair this tool installation before retrying.')
        root.parent.mkdir(parents=True, exist_ok=True)
        notify({'phase': 'checking', 'message': 'Downloading the pinned Block Party preparation tool'})
        staging = root.parent / (BLOCK_PARTY_COMMIT + '.download-' + uuid4().hex)
        result = subprocess.run(['git', 'clone', '--no-checkout', '--filter=blob:none', BLOCK_PARTY_REPOSITORY, str(staging)],
            capture_output=True, timeout=240, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise SetupError('Could not download Block Party. Check Git and Internet access, then retry.')
        _git(staging, 'checkout', '--detach', BLOCK_PARTY_COMMIT)
        staging.rename(root)
    if _git(root, 'rev-parse', 'HEAD') != BLOCK_PARTY_COMMIT or _git(root, 'status', '--porcelain', '--untracked-files=normal'):
        raise SetupError('The private Block Party tool changed. No dependency installer was run.')
    existing = sys.modules.get('one_job')
    if existing and Path(existing.__file__).resolve().parent != root.resolve() / 'one_job':
        raise SetupError('A different Block Party runtime is already loaded. Restart the Darius API before preparing boards.')
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    provision = importlib.import_module('one_job.provision')
    slots = importlib.import_module('one_job.slots')
    if 'SaveImageAdvanced' not in slots.IMAGE_SAVERS:
        slots.IMAGE_SAVERS += ('SaveImageAdvanced',)
    try:
        from .comfy_host import install_block_party_adapter
    except ImportError as error:
        raise SetupError('Run Install / repair from the Darius manager to install native process inspection, then restart Darius.') from error
    install_block_party_adapter()
    return provision


def _link(settings):
    from .comfy_connection import effective_settings, detect, save
    settings = effective_settings(settings)
    root = comfy_root(settings)
    endpoint = urlparse(settings.comfyui_base_url)
    if not root:
        try:
            found = detect(settings)
            save(settings, found['root'], found['baseUrl'], output_dir=found['outputDir'])
            settings = effective_settings(settings)
            root = comfy_root(settings)
        except (ValueError, OSError) as error:
            raise SetupError('Connect ComfyUI below: use Detect ComfyUI, or enter its folder on the Darius computer.') from error
    if endpoint.scheme != 'http' or endpoint.hostname not in {'127.0.0.1', 'localhost', '::1'} or endpoint.username or endpoint.password:
        raise SetupError('Board preparation requires the ComfyUI installation on this server and its loopback HTTP endpoint.')
    from one_job.host import link_from_folder
    link = link_from_folder(root, settings.comfyui_base_url)
    if not link:
        raise SetupError('Could not identify the ComfyUI Python environment. Use a supported portable or virtual-environment ComfyUI installation.')
    return link


def _summary(plan):
    return [{key: action[key] for key in ('kind', 'filename', 'folder', 'name', 'git_url', 'commit', 'size_bytes', 'auth', 'url') if key in action}
            for action in plan['actions']]


def _compatibility_job(directory):
    """A preparation-only host-extension recipe; it is never queued for rendering."""
    directory = directory / 'host-compatibility'
    atomic_json(directory / 'workflow.api.json', {
        '1': {'class_type': 'EmptyImage', 'inputs': {'width': 64, 'height': 64, 'batch_size': 1, 'color': 0}},
        '2': {'class_type': 'SaveImage', 'inputs': {'images': ['1', 0], 'filename_prefix': 'unused-preparation-check'}}})
    atomic_json(directory / 'manifest.json', {
        'name': 'darius-h3-host-compatibility', 'workflows': [{'name': 'default', 'file': 'workflow.api.json'}],
        'models': [], 'inputs': [], 'parameters': [],
        'outputs': [{'name': 'image_0', 'node_id': '2', 'class_type': 'SaveImage'}],
        'nodes': [{'name': 'Comfyui_BlockParty', 'git_url': BLOCK_PARTY_REPOSITORY,
                   'commit': BLOCK_PARTY_COMMIT, 'class_types': []}]})
    return directory


def _compatibility_loaded(link):
    try:
        with urllib.request.urlopen(link.url.rstrip('/') + '/block_party/h3_status', timeout=5) as response:
            return json.load(response).get('version') == 2
    except (OSError, ValueError):
        return False


def _missing_nodes(link, graph, manifest):
    from one_job.job import ensure_server
    from one_job.comfy import _request
    ensure_server(link)
    registered = json.loads(_request(link.url.rstrip('/') + '/object_info')[1])
    declared = {kind for pack in manifest.get('nodes', []) for kind in pack.get('class_types', [])}
    needed = {node['class_type'] for node in graph.values()}
    return sorted(needed - declared - registered.keys()), sorted((needed & declared) - registered.keys())


def _prepare_local_sources(directory, link, graph, manifest, full_manifest, receipts):
    """Darius readiness for exact local sources; never fabricate a Git preparation receipt."""
    from .board_node_reuse import receipt_matches, reuse_body_swap
    from one_job.job import check_contract, verify_nodes, verify_models, verify_registered_nodes
    from one_job.runtime_requirements import verify_runtime_requirements
    if (json.loads((directory / 'workflow.api.json').read_text(encoding='utf-8')) != graph
            or json.loads((directory / 'manifest.json').read_text(encoding='utf-8')) != manifest):
        raise SetupError('The board dependency contract changed during verification.')
    if not receipt_matches(link.comfy_root, receipts):
        raise SetupError('Reviewed local node sources changed during preparation.')
    # Block Party's Git inventory intentionally excludes development junctions.
    # Verify those packs through Darius's exact source/loaded-owner receipts;
    # retain Block Party's full contract, model, upstream Git and runtime checks.
    check_contract(graph, full_manifest)
    verify_nodes(Path(link.custom_nodes), manifest)
    verify_models(Path(link.comfy_root), full_manifest, graph)
    verify_registered_nodes(link, graph)
    verify_runtime_requirements(directory, link, graph, full_manifest)
    if not receipt_matches(link.comfy_root, receipts) or reuse_body_swap(full_manifest, link)[1] != receipts:
        raise SetupError('Reviewed local node sources changed during preparation.')


def _run(settings, profile, confirmed, restart):
    base = {'state': 'preparing' if confirmed else 'checking'}
    last = [0.0]

    def notify(event):
        # Persist bounded progress, never a command, credential or full diagnostic.
        if time.monotonic() - last[0] < .3:
            return
        last[0] = time.monotonic()
        progress = {key: event[key] for key in ('phase', 'message', 'filename', 'bytes_done', 'bytes_total') if key in event}
        if event.get('bytes_per_second') is not None:
            progress['speed'] = event['bytes_per_second']
        if event.get('eta_seconds') is not None:
            progress['eta'] = event['eta_seconds']
        _write(settings, profile, **base, progress=progress)

    try:
        spec, graph = package(settings, profile)
        base['packageDigest'] = digest(spec)
        with _host_lock, _private_home(settings):
            provision = runtime(settings, notify)
            from one_job.progress import reporting
            from one_job.job import prepare_job
            link = _link(settings)
            from .comfy_connection import effective_settings
            settings = effective_settings(settings)
            directory = _directory(settings, profile)
            from .board_node_reuse import reuse_installed
            manifest, reused = reuse_installed(profile, spec['manifest'], link)
            base['reusedNodes'] = reused
            if reused:
                notify({'phase': 'checking', 'message': 'Reusing installed nodes: source fingerprints and loaded ownership match the reviewed implementation. No node files will be changed.'})
            # Only declarative, source-pinned graph/manifest files are materialized.
            atomic_json(directory / 'workflow.api.json', graph)
            atomic_json(directory / 'manifest.json', manifest)
            with reporting(notify):
                if any(node.get('class_type') == 'H3Keyframes' for node in graph.values()) and not _compatibility_loaded(link):
                    host_job = _compatibility_job(directory)
                    host_plan = provision.plan_job(host_job, link)
                    base.update(actions=_summary(host_plan), blocked=host_plan['blocked'], planDigest=host_plan['digest'], stage='compatibility')
                    if host_plan['blocked']:
                        _write(settings, profile, **{**base, 'state': 'blocked', 'message': 'ComfyUI compatibility setup needs attention.'})
                        return
                    if not confirmed:
                        _write(settings, profile, **{**base, 'state': 'needs_setup', 'message': 'Install/load Block Party H3 compatibility first. ComfyUI must be idle for its restart. Model preparation follows this step.'})
                        return
                    if host_plan['digest'] != confirmed:
                        raise SetupError('ComfyUI compatibility plan changed. Check and review the updated plan.')
                    if not restart:
                        raise SetupError('This compatibility step requires restarting the verified idle ComfyUI. Enable restart, or install/load Block Party manually and check again.')
                    provision.provision_job(host_job, link, confirmed, restart=True)
                    if not _compatibility_loaded(link):
                        from one_job.lifecycle import restart_server
                        restart_server(link)
                    if not _compatibility_loaded(link):
                        raise SetupError('ComfyUI did not load the Block Party H3 compatibility extension. Check its startup log, then check this board again.')
                    # The second confirmation reviews the actual model download
                    # plan after the new host extension has been loaded.
                    confirmed = None
                    base['state'] = 'checking'
                    base.pop('stage', None)
                plan = provision.plan_job(directory, link)
                missing_core, missing_custom = _missing_nodes(link, graph, spec['manifest'])
                if missing_core:
                    plan['blocked'].append('Update ComfyUI and restart it before preparing this board. Missing built-in nodes: ' + ', '.join(missing_core))
                if confirmed and plan['digest'] != confirmed:
                    raise SetupError('The dependency plan changed. Check again and review the updated download list.')
                base.update(actions=_summary(plan), blocked=plan['blocked'], planDigest=plan['digest'])
                if plan['blocked']:
                    _write(settings, profile, **{**base, 'state': 'blocked', 'message': 'Resolve the listed dependencies, then check again.'})
                    return
                if not confirmed and (plan['actions'] or missing_custom):
                    _write(settings, profile, **{**base, 'state': 'needs_setup', 'message': 'Prepare these dependencies once; installed shared files are reused.'})
                    return
                if confirmed:
                    pending_classes = {kind for action in plan['actions'] if action['kind'] == 'node' for kind in action.get('class_types', [])}
                    if set(missing_custom) - pending_classes:
                        if not restart:
                            raise SetupError('Installed custom nodes are not loaded. Restart ComfyUI, or enable the idle restart option, then check again.')
                        from one_job.lifecycle import restart_server
                        restart_server(link)
                    try:
                        provision.provision_job(directory, link, confirmed, restart=restart)
                    except Exception as error:
                        local_classes = {'DariusOllamaH3SwapPrompt', 'DariusOllamaModel', 'RecastH3PrepareVideo', 'RecastH3Release', 'RecastVideoSize'}
                        if (not any(r.get('scheme') == 'source-files-v1' for r in reused)
                                or getattr(error, 'code', None) != 'missing_node'
                                or not any(str(error).startswith(kind + ' is not declared') for kind in local_classes)):
                            raise
                        _prepare_local_sources(directory, link, graph, manifest, spec['manifest'], reused)
                else:
                    if any(r.get('scheme') == 'source-files-v1' for r in reused):
                        _prepare_local_sources(directory, link, graph, manifest, spec['manifest'], reused)
                    else:
                        prepare_job(directory, link)
                _write(settings, profile, **{**base, 'state': 'ready', 'message': 'This board is ready. Generate uses your saved board draft.'})
    except Exception as error:
        code = getattr(error, 'code', 'setup_failed')
        _log.warning('Board setup failed: profile=%s code=%s exception=%s', profile, code, type(error).__name__)
        # Block Party's structured errors are designed for display. Unexpected
        # exceptions may contain signed URLs or credentials: keep those private.
        message = str(error) if isinstance(error, SetupError) else getattr(error, 'message', 'Preparation could not finish. Check the configured ComfyUI installation and retry.')
        if code == 'host_mismatch':
            from .comfy_host import failure_message
            message = failure_message(settings.comfyui_base_url, comfy_root(settings), reachable=True)
        elif code == 'node_version_conflict':
            message += '. Check again cannot resolve a version conflict. Keep your existing nodes; this board requires its pinned revision or a verified compatible implementation. Unloaded, modified or incompatible node packs cannot be reused automatically.'
        from .diagnostics import record
        record(settings, 'board_setup', 'error', 'preparation_failed', profile=profile, code=code, message=message)
        _write(settings, profile, **{**base, 'state': 'restart_required' if code == 'restart_required' else 'failed', 'message': message, 'code': code})
    finally:
        with _guard:
            _active.discard(_key(settings, profile))
            _preparing.discard(_key(settings, profile))


def begin(settings, profile, *, confirmed=None, restart=False):
    spec, _ = package(settings, profile)
    key = _key(settings, profile)
    with _guard:
        if key in _active:
            return status(settings, profile)
        if confirmed:
            current = status(settings, profile)
            if current.get('state') not in {'needs_setup', 'restart_required'} or current.get('planDigest') != confirmed:
                raise SetupError('Check and review this board dependency plan before preparing it.')
        _active.add(key)
        if confirmed:
            _preparing.add(key)
        _write(settings, profile, packageDigest=digest(spec), state='preparing' if confirmed else 'checking',
            message='Preparing board dependencies' if confirmed else 'Checking installed models and nodes; large files can take a moment.')
        thread = threading.Thread(target=_run, args=(settings, profile, confirmed, restart), daemon=True, name='board-setup')
        try:
            thread.start()
        except RuntimeError as error:
            _active.discard(key)
            _preparing.discard(key)
            _write(settings, profile, packageDigest=digest(spec), state='failed', message='Could not start board preparation. No dependencies were changed; retry the check.')
            raise SetupError('Could not start board preparation. Retry the check.') from error
        return status(settings, profile)


def preparation_running(settings):
    directory = getattr(settings, 'data_dir', None)
    if directory is None:
        return False
    prefix = str(directory.resolve())
    with _guard:
        return any(key[0] == prefix for key in _preparing)


def host_installation_locked(settings):
    root = comfy_root(settings) if getattr(settings, 'block_party_comfy_root', None) or getattr(settings, 'comfyui_output_dir', None) else None
    return bool(root and (root / '.block-party-provision.lock').exists()) or preparation_running(settings)
