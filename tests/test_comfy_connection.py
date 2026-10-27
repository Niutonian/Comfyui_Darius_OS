from dataclasses import replace
from types import SimpleNamespace
import json

import pytest

from darius_api import comfy_connection as connection
from darius_api import board_setup
from darius_api.providers import ComfyMcpProvider
from test_media_backend import settings_for


def comfy(tmp_path):
    root = tmp_path / 'ComfyUI'
    root.mkdir()
    (root / 'main.py').write_text('')
    (root / 'folder_paths.py').write_text('')
    (root / 'output').mkdir()
    return root


def test_saved_connection_is_used_by_existing_provider_and_future_settings(tmp_path):
    settings = settings_for(tmp_path)
    root = comfy(tmp_path)
    result = connection.save(settings, str(root), 'http://127.0.0.1:8188')
    assert result['configured']
    current = connection.effective_settings(settings)
    assert current.comfyui_output_dir == root / 'output'
    assert current.block_party_comfy_root == root
    assert ComfyMcpProvider(settings).settings.comfyui_base_url == 'http://127.0.0.1:8188'
    assert settings.comfyui_base_url == 'http://127.0.0.1:1'
    assert current.database_url == settings.database_url
    assert current.openai_api_key == settings.openai_api_key


def test_bad_folder_and_remote_address_never_replace_valid_connection(tmp_path):
    settings = settings_for(tmp_path)
    root = comfy(tmp_path)
    connection.save(settings, str(root), 'http://localhost:8188')
    previous = connection.connection_file(settings).read_bytes()
    with pytest.raises(ValueError):
        connection.save(settings, str(tmp_path / 'missing'), 'http://localhost:8188')
    with pytest.raises(ValueError):
        connection.save(settings, str(root), 'https://remote.example')
    assert connection.connection_file(settings).read_bytes() == previous


def test_portable_parent_and_windows_copy_as_path_are_accepted(tmp_path):
    settings = settings_for(tmp_path)
    root = comfy(tmp_path)
    value = connection.save(settings, '"' + str(root.parent) + '"', 'http://localhost:8188')
    assert value['root'] == str(root)


def test_private_cli_replaces_only_missing_placeholder_command(tmp_path):
    settings = replace(settings_for(tmp_path), comfy_mcp_command='C:/path/to/comfy.exe')
    executable = settings.data_dir / 'tools/comfy-cli/1.17.0/venv/Scripts/comfy.exe'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'fixture')
    assert connection.effective_settings(settings).comfy_mcp_command == str(executable)
    own = tmp_path / 'my-comfy.exe'
    own.write_bytes(b'fixture')
    assert connection.effective_settings(replace(settings, comfy_mcp_command=str(own))).comfy_mcp_command == str(own)


def test_private_cli_takes_precedence_over_an_unknown_version_on_path(tmp_path, monkeypatch):
    settings = replace(settings_for(tmp_path), comfy_mcp_command='comfy')
    executable = settings.data_dir / 'tools/comfy-cli/1.17.0/venv/Scripts/comfy.exe'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'fixture')
    monkeypatch.setattr(connection.shutil, 'which', lambda *args: 'some-older-global-comfy')
    assert connection.effective_settings(settings).comfy_mcp_command == str(executable)


def test_link_detects_and_saves_running_host_instead_of_requiring_env_edits(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    root = comfy(tmp_path)
    found = {'root': str(root), 'baseUrl': 'http://localhost:8188', 'outputDir': str(root / 'output')}
    monkeypatch.setattr(connection, 'detect', lambda *args: found)
    import sys
    from types import ModuleType
    host = ModuleType('one_job.host')
    host.link_from_folder = lambda root, url: SimpleNamespace(comfy_root=str(root), url=url)
    monkeypatch.setitem(sys.modules, 'one_job.host', host)
    linked = board_setup._link(settings)
    assert linked.comfy_root == str(root)
    assert connection.effective_settings(settings).comfyui_output_dir == root / 'output'


def test_connection_switch_does_not_change_active_task_identity(tmp_path):
    settings = settings_for(tmp_path)
    key = board_setup._key(settings, 'moss-bboxes-v1')
    root = comfy(tmp_path)
    connection.save(settings, str(root), 'http://localhost:8188')
    assert board_setup._key(settings, 'moss-bboxes-v1') == key


def test_new_worker_settings_use_saved_connection_and_custom_output(tmp_path, monkeypatch):
    from darius_api.config import Settings
    settings = settings_for(tmp_path)
    root = comfy(tmp_path)
    output = tmp_path / 'finished renders'
    output.mkdir()
    connection.save(settings, str(root), 'http://localhost:8288', output_dir='"' + str(output) + '"')
    monkeypatch.setenv('DARIUS_DATA_DIR', str(settings.data_dir))
    loaded = Settings.from_env()
    assert loaded.comfyui_base_url == 'http://localhost:8288'
    assert loaded.comfyui_output_dir == output
    assert loaded.block_party_comfy_root == root


def test_detection_preserves_absolute_output_flag_without_exposing_launch_arguments(tmp_path, monkeypatch):
    import sys
    from types import ModuleType
    settings = settings_for(tmp_path)
    root = comfy(tmp_path)
    output = tmp_path / 'custom output'
    output.mkdir()
    monkeypatch.setattr(board_setup, 'runtime', lambda *args: None)
    host = ModuleType('one_job.host')
    host.link_from_running_server = lambda *args: SimpleNamespace(comfy_root=str(root), comfy_output=str(root / 'output'))
    api = ModuleType('one_job.comfy')
    api._request = lambda *args: (200, json.dumps({'system': {'argv': ['main.py', '--output-directory', str(output), '--private-flag', 'private-value']}}).encode())
    monkeypatch.setitem(sys.modules, 'one_job.host', host)
    monkeypatch.setitem(sys.modules, 'one_job.comfy', api)
    value = connection.detect(settings)
    assert value['outputDir'] == str(output)
    assert 'private-value' not in json.dumps(value)
    assert not connection.connection_file(settings).exists()
