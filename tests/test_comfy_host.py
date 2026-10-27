from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import psutil
import pytest

from darius_api import comfy_host as host


@pytest.fixture
def machine(tmp_path, monkeypatch):
    core = tmp_path / 'install with spaces' / 'ComfyUI'
    core.mkdir(parents=True)
    (core / 'main.py').write_text('')
    (core / 'folder_paths.py').write_text('')
    python = tmp_path / 'unrelated global Python' / 'python.exe'
    python.parent.mkdir()
    python.write_bytes(b'fixture')
    arguments = [str(python), '-s', 'main.py', '--listen', '127.0.0.1', '--port', '8188']
    process = SimpleNamespace(create_time=lambda: 123.0, exe=lambda: str(python),
        cmdline=lambda: list(arguments), cwd=lambda: str(core), is_running=lambda: True)
    monkeypatch.setattr(host.psutil, 'Process', lambda pid: process)
    return core, python, arguments, process


def test_relative_main_uses_actual_cwd_outside_interpreter_ancestors(machine):
    core, python, arguments, _ = machine
    identity = host.process_identity(55)
    assert identity.main == core / 'main.py'
    assert identity.arguments[2] == str(core / 'main.py')
    assert identity.arguments[3:] == tuple(arguments[3:])
    assert str(python.parent) not in str(identity.main)


def test_absolute_main_does_not_require_access_to_cwd(machine):
    core, _, arguments, process = machine
    arguments[2] = str(core / 'main.py')
    def denied():
        raise psutil.AccessDenied(55)
    process.cwd = denied
    assert host.process_identity(55).main == core / 'main.py'


def test_portable_comfyui_subdirectory_is_resolved_against_launcher_cwd(machine):
    core, _, arguments, process = machine
    arguments[2] = 'ComfyUI/main.py'
    process.cwd = lambda: str(core.parent)
    assert host.process_identity(55).main == core / 'main.py'


def test_relative_main_without_cwd_is_not_guessed_from_other_installs(machine):
    _, python, arguments, _ = machine
    (python.parent / 'main.py').write_text('')
    (python.parent / 'folder_paths.py').write_text('')
    with pytest.raises(host.InspectionError, match='working_folder_unavailable'):
        host.main_path(arguments)


@pytest.mark.parametrize('arguments', [
    ['python.exe', '-c', 'print("main.py")'],
    ['python.exe', '-m', 'some_module', 'main.py'],
    ['python.exe', 'other_server.py', 'main.py'],
])
def test_main_py_in_unrelated_arguments_is_not_ownership_proof(arguments):
    assert host.script_index(arguments) is None


def test_python_options_and_delimiter_preserve_script_identity():
    assert host.script_index(['python', '-X', 'utf8', '-W', 'ignore', '-s', 'main.py']) == 6
    assert host.script_index(['python', '--', 'main.py']) == 2


def test_access_denied_and_pid_reuse_are_reported_without_trusting_the_process(machine):
    _, _, _, process = machine
    process.is_running = lambda: False
    with pytest.raises(host.InspectionError, match='process_changed'):
        host.process_identity(55)
    def denied():
        raise psutil.AccessDenied(55)
    process.cmdline = denied
    with pytest.raises(host.InspectionError, match='permission_denied'):
        host.process_identity(55)


def test_verified_venv_launcher_is_retained_for_restart_and_pip(machine):
    core, python, arguments, _ = machine
    launcher = core / '.venv/Scripts/python.exe'
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b'fixture')
    (launcher.parent.parent / 'pyvenv.cfg').write_text('home = ' + str(python.parent))
    arguments[0] = str(launcher)
    assert host.process_identity(55).executable == str(launcher)


def row(pid, ip='127.0.0.1', port=8188, state=psutil.CONN_LISTEN):
    return SimpleNamespace(pid=pid, laddr=SimpleNamespace(ip=ip, port=port), status=state)


def test_listener_lookup_is_locale_independent_and_ignores_other_ports(monkeypatch):
    monkeypatch.setattr(host.psutil, 'net_connections', lambda **kwargs: [
        row(10, '0.0.0.0'), row(20, port=9000), row(30, state=psutil.CONN_ESTABLISHED), row(40, '192.0.2.10')])
    assert host.listening_pid(8188) == 10


def test_two_localhost_backends_are_not_guessed(monkeypatch):
    monkeypatch.setattr(host.psutil, 'net_connections', lambda **kwargs: [row(10), row(20, '::1')])
    with pytest.raises(host.InspectionError, match='multiple_listeners'):
        host.listening_pid(8188, 'localhost')
    assert host.listening_pid(8188, '127.0.0.1') == 10


def test_wrong_folder_is_rejected_and_privilege_error_is_actionable(machine, monkeypatch):
    core, _, _, process = machine
    monkeypatch.setattr(host, 'listening_pid', lambda *args: 55)
    assert 'different installation' in host.failure_message('http://127.0.0.1:8188', core.parent)
    def denied():
        raise psutil.AccessDenied(55)
    process.cmdline = denied
    assert 'administrator' in host.failure_message('http://127.0.0.1:8188', core)


def test_adapter_does_not_replace_server_verification_or_restart_guards(monkeypatch):
    block_host = ModuleType('one_job.host')
    lifecycle = ModuleType('one_job.lifecycle')
    lifecycle.restart_server = lambda *args: None
    job = ModuleType('one_job.job')
    job.ensure_server = lambda *args: None
    verification = job.ensure_server
    restart = lifecycle.restart_server
    monkeypatch.setitem(sys.modules, 'one_job.host', block_host)
    monkeypatch.setitem(sys.modules, 'one_job.lifecycle', lifecycle)
    monkeypatch.setitem(sys.modules, 'one_job.job', job)
    host.install_block_party_adapter()
    assert job.ensure_server is verification
    assert lifecycle.restart_server is restart
    assert block_host._darius_native_inspection is True
