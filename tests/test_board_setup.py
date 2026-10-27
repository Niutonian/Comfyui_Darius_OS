"""Board setup is declarative, host-bound and separate from render submission."""
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from darius_api import board_setup as setup
REAL_PROFILE_GRAPH = setup.profile_graph


@pytest.fixture
def machine(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    catalog = root / 'workflows/board-setup'
    catalog.mkdir(parents=True)
    graph = {'1': {'class_type': 'SaveImage', 'inputs': {}}}
    spec = {'profile': 'moss-bboxes-v1', 'graphDigest': setup.digest(graph),
            'manifest': {'models': [], 'nodes': []}}
    (catalog / 'moss-bboxes-v1.json').write_text(json.dumps(spec))
    comfy = tmp_path / 'comfy'
    comfy.mkdir()
    (comfy / 'main.py').write_text('')
    (comfy / 'folder_paths.py').write_text('')
    settings = SimpleNamespace(repository_root=root, data_dir=tmp_path / 'data',
        block_party_comfy_root=comfy, comfyui_output_dir=comfy / 'output', comfyui_base_url='http://127.0.0.1:8188')
    monkeypatch.setattr(setup, 'profile_graph', lambda settings, profile: graph)
    monkeypatch.setattr(setup, '_active', set())
    monkeypatch.setattr(setup, '_preparing', set())
    monkeypatch.setattr(setup, '_missing_nodes', lambda *args: ([], []))
    calls = []
    plan = {'digest': 'a' * 64, 'actions': [{'kind': 'model', 'filename': 'model.safetensors', 'size_bytes': 12,
        'destination': '/private/host/models/model.safetensors'}], 'blocked': []}
    provision = SimpleNamespace(plan_job=lambda *args: plan, provision_job=lambda *args, **kwargs: calls.append('provision'))
    monkeypatch.setattr(setup, 'runtime', lambda *args: provision)
    monkeypatch.setattr(setup, '_link', lambda *args: SimpleNamespace())
    progress = ModuleType('one_job.progress')
    progress.reporting = lambda *args: nullcontext()
    job = ModuleType('one_job.job')
    job.prepare_job = lambda *args: calls.append('verify-existing')
    monkeypatch.setitem(sys.modules, 'one_job.progress', progress)
    monkeypatch.setitem(sys.modules, 'one_job.job', job)
    return settings, spec, plan, calls


def test_check_only_produces_plan_and_does_not_install_or_render(machine):
    settings, _, _, calls = machine
    setup._run(settings, 'moss-bboxes-v1', None, False)
    state = setup.status(settings, 'moss-bboxes-v1')
    assert state['state'] == 'needs_setup'
    assert calls == []
    assert 'destination' not in state['actions'][0]
    assert '/private/' not in json.dumps(state)


def test_changed_plan_is_rejected_before_any_install(machine):
    settings, _, _, calls = machine
    setup._run(settings, 'moss-bboxes-v1', 'b' * 64, True)
    assert setup.status(settings, 'moss-bboxes-v1')['state'] == 'failed'
    assert calls == []


def test_confirmed_plan_prepares_without_submitting_any_render(machine):
    settings, _, plan, calls = machine
    setup._run(settings, 'moss-bboxes-v1', plan['digest'], True)
    assert setup.status(settings, 'moss-bboxes-v1')['state'] == 'ready'
    assert calls == ['provision']


def test_missing_source_blocks_installation(machine):
    settings, _, plan, calls = machine
    plan['blocked'] = ['Author must provide the original download URL']
    setup._run(settings, 'moss-bboxes-v1', plan['digest'], True)
    assert setup.status(settings, 'moss-bboxes-v1')['state'] == 'blocked'
    assert calls == []


def test_existing_dependencies_are_verified_without_reinstall(machine):
    settings, _, plan, calls = machine
    plan['actions'] = []
    setup._run(settings, 'moss-bboxes-v1', None, False)
    assert setup.status(settings, 'moss-bboxes-v1')['state'] == 'ready'
    assert calls == ['verify-existing']


def test_reused_node_commit_reaches_private_manifest_without_changing_package(machine, monkeypatch):
    from darius_api import board_node_reuse
    settings, spec, plan, _ = machine
    plan['actions'] = []
    original = json.loads(json.dumps(spec))
    receipt = {'name': 'comfyui-kjnodes', 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    manifest = {'models': [], 'nodes': [{'name': 'comfyui-kjnodes', 'commit': 'a' * 40}]}
    monkeypatch.setattr(board_node_reuse, 'reuse_installed', lambda *args: (manifest, [receipt]))
    monkeypatch.setattr(board_node_reuse, 'receipt_matches', lambda *args: True)
    setup._run(settings, 'moss-bboxes-v1', None, False)
    assert spec == original
    assert json.loads((setup._directory(settings, 'moss-bboxes-v1') / 'manifest.json').read_text()) == manifest
    assert setup.status(settings, 'moss-bboxes-v1')['reusedNodes'] == [receipt]
    monkeypatch.setattr(board_node_reuse, 'receipt_matches', lambda *args: False)
    assert setup.status(settings, 'moss-bboxes-v1')['state'] == 'unchecked'


def test_changed_package_or_host_invalidates_saved_readiness(machine):
    settings, spec, plan, _ = machine
    plan['actions'] = []
    setup._run(settings, 'moss-bboxes-v1', None, False)
    settings.comfyui_base_url = 'http://127.0.0.1:9191'
    assert setup.status(settings, 'moss-bboxes-v1')['state'] == 'unchecked'
    settings.comfyui_base_url = 'http://127.0.0.1:8188'
    spec['manifest']['models'] = [{'filename': 'different'}]
    (settings.repository_root / 'workflows/board-setup/moss-bboxes-v1.json').write_text(json.dumps(spec))
    assert setup.status(settings, 'moss-bboxes-v1')['state'] == 'unchecked'


def test_crashed_preparation_is_reported_as_interrupted(machine):
    settings, spec, _, _ = machine
    setup._write(settings, 'moss-bboxes-v1', packageDigest=setup.digest(spec), state='preparing')
    assert setup.status(settings, 'moss-bboxes-v1')['state'] == 'interrupted'


def test_unexpected_errors_do_not_expose_credentials(machine, monkeypatch):
    settings, _, _, _ = machine
    def fail(*args):
        raise RuntimeError('signed-url-with-private-credential')
    monkeypatch.setattr(setup, 'runtime', fail)
    setup._run(settings, 'moss-bboxes-v1', None, False)
    assert 'private-credential' not in json.dumps(setup.status(settings, 'moss-bboxes-v1'))


def test_core_node_missing_blocks_downloads_before_install(machine, monkeypatch):
    settings, _, plan, calls = machine
    monkeypatch.setattr(setup, '_missing_nodes', lambda *args: (['NewCoreNode'], []))
    setup._run(settings, 'moss-bboxes-v1', plan['digest'], True)
    state = setup.status(settings, 'moss-bboxes-v1')
    assert state['state'] == 'blocked'
    assert 'Update ComfyUI' in state['blocked'][0]
    assert calls == []


def test_preparation_uses_private_home_and_restores_environment(machine, monkeypatch):
    settings, _, _, _ = machine
    monkeypatch.setenv('ONE_JOB_HOME', 'existing-block-party-home')
    with setup._private_home(settings):
        import os
        assert os.environ['ONE_JOB_HOME'].startswith(str(settings.data_dir))
    assert os.environ['ONE_JOB_HOME'] == 'existing-block-party-home'


def test_unknown_profile_cannot_escape_the_catalog(machine, monkeypatch):
    settings, _, _, _ = machine
    monkeypatch.setattr(setup, 'profile_graph', REAL_PROFILE_GRAPH)
    with pytest.raises(setup.SetupError, match='Unknown board'):
        setup.package(settings, '../../.env')


def test_prepare_endpoint_requires_checked_digest_and_rejects_arbitrary_actions(machine):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from darius_api.canvas_api import router
    settings, _, _, calls = machine
    app = FastAPI()
    app.include_router(router(settings, None, None))
    with TestClient(app) as client:
        response = client.post('/api/v1/canvas/setup/moss-bboxes-v1/prepare', json={'planDigest': 'a' * 64})
        assert response.status_code == 409
        assert 'review' in response.json()['detail']
        response = client.post('/api/v1/canvas/setup/moss-bboxes-v1/prepare', json={'planDigest': 'a' * 64, 'actions': [{'url': 'https://example.invalid'}]})
        assert response.status_code == 422
    assert not calls


def test_published_packages_cover_all_profiles_and_keep_graph_pins():
    from darius_api.config import Settings
    settings = Settings.from_env()
    from darius_api import canvas_fibo, canvas_h3, canvas_images, canvas_moss
    profiles = {canvas_moss.VERSION, *canvas_fibo.PROFILES, *canvas_h3.PROFILES, *canvas_images.PROFILES}
    assert len(profiles) == 11
    for profile in profiles:
        spec, graph = setup.package(settings, profile)
        assert spec['graphDigest'] == setup.digest(graph)
        for model in spec['manifest']['models']:
            assert len(model['sha256']) == 64
            assert model['size_bytes'] > 0
        for node in spec['manifest']['nodes']:
            assert len(node['commit']) == 40
            assert node['git_url'].startswith('https://')
