"""OS-backed ComfyUI ownership checks; no shell/WMI or process control here."""
from dataclasses import dataclass, field
import importlib
import ipaddress
import os
from pathlib import Path
import re
import shlex
import subprocess
from urllib.parse import urlsplit

import psutil


class InspectionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created: float
    executable: str = field(repr=False)
    arguments: tuple[str, ...] = field(repr=False)
    main: Path = field(repr=False)


def script_index(arguments):
    """Inspect Python's script argument, never a main.py mentioned in other data."""
    index = 1
    while index < len(arguments):
        value = arguments[index]
        if value in {'-m', '-c', '--'}:
            if value != '--':
                return None
            index += 1
            return index if index < len(arguments) and Path(arguments[index]).name.lower() == 'main.py' else None
        if value in {'-X', '-W', '--check-hash-based-pycs'}:
            index += 2
            continue
        if value.startswith('-'):
            index += 1
            continue
        return index if Path(value).name.lower() == 'main.py' else None
    return None


def main_path(arguments, cwd=None):
    index = script_index(arguments)
    if index is None:
        raise InspectionError('unrecognized_launcher')
    main = Path(arguments[index])
    if not main.is_absolute():
        if not cwd:
            raise InspectionError('working_folder_unavailable')
        main = Path(cwd) / main
    main = main.resolve()
    if not main.is_file() or not (main.parent / 'folder_paths.py').is_file():
        raise InspectionError('comfy_folder_unavailable')
    return main, index


def listening_pid(port, host='127.0.0.1'):
    try:
        port = int(port)
        if host == 'localhost':
            allowed = {'127.0.0.1', '::1', '0.0.0.0', '::'}
        else:
            target = ipaddress.ip_address(host)
            if not target.is_loopback:
                raise InspectionError('not_loopback')
            allowed = {str(target), '::' if target.version == 6 else '0.0.0.0'}
            # Dual-stack Windows listeners may appear only as IPv6 wildcard.
            if target.version == 4:
                allowed.add('::')
        matches = {row.pid for row in psutil.net_connections(kind='tcp')
                   if row.status == psutil.CONN_LISTEN and row.laddr and row.laddr.port == port
                   and row.laddr.ip in allowed and row.pid}
    except psutil.AccessDenied as error:
        raise InspectionError('permission_denied') from error
    if len(matches) > 1:
        raise InspectionError('multiple_listeners')
    if not matches:
        raise InspectionError('no_listener')
    return next(iter(matches))


def process_identity(pid):
    try:
        process = psutil.Process(pid)
        created = process.create_time()
        executable = process.exe()
        if not re.fullmatch(r'(?:python(?:w|\d+(?:\.\d+)*)?|pypy\d*)(?:\.exe)?', Path(executable).name, re.I):
            raise InspectionError('unrecognized_launcher')
        arguments = list(process.cmdline())
        index = script_index(arguments)
        if index is None:
            raise InspectionError('unrecognized_launcher')
        cwd = process.cwd() if not Path(arguments[index]).is_absolute() else None
        main, index = main_path(arguments, cwd)
        arguments[index] = str(main)
        # Keep the actual venv launcher when its declared base interpreter is
        # the executable observed by the OS (Windows Python redirectors).
        launcher = Path(arguments[0]) if arguments else None
        if launcher and launcher.is_absolute() and launcher.is_file():
            config = launcher.parent.parent / 'pyvenv.cfg'
            if config.is_file():
                for line in config.read_text(encoding='utf-8-sig').splitlines():
                    key, separator, value = line.partition('=')
                    if separator and key.strip().lower() == 'home':
                        if Path(value.strip()).resolve() == Path(executable).resolve().parent:
                            executable = str(launcher)
        if not process.is_running():
            raise InspectionError('process_changed')
        return ProcessIdentity(pid, created, executable, tuple(arguments), main)
    except psutil.AccessDenied as error:
        raise InspectionError('permission_denied') from error
    except (psutil.NoSuchProcess, psutil.ZombieProcess) as error:
        raise InspectionError('process_changed') from error


def _same_root(left, right):
    try:
        return Path(left).samefile(Path(right))
    except OSError:
        return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def install_block_party_adapter():
    """Adapt only the private runtime's inspection helpers, never its guards."""
    host = importlib.import_module('one_job.host')
    if getattr(host, '_darius_native_inspection', False):
        return

    def pid_for(port, hostname='127.0.0.1'):
        try:
            return listening_pid(port, hostname)
        except (InspectionError, OSError, ValueError):
            return None

    def command_for(pid):
        try:
            identity = process_identity(pid)
            command = subprocess.list2cmdline(identity.arguments) if os.name == 'nt' else shlex.join(identity.arguments)
            return identity.executable, command
        except (InspectionError, OSError, ValueError):
            return None, None

    def resolve_main(executable, command):
        if not command:
            return None
        try:
            lifecycle = importlib.import_module('one_job.lifecycle')
            arguments = lifecycle.command_args(command)
            return main_path(arguments)[0]  # Already normalized against the OS cwd.
        except (InspectionError, OSError, ValueError):
            return None

    host._listening_pid = pid_for
    host._process_command = command_for
    host._resolve_main = resolve_main
    # lifecycle imports these by name; update already-loaded references too.
    lifecycle = importlib.import_module('one_job.lifecycle')
    lifecycle._listening_pid = pid_for
    lifecycle._process_command = command_for
    lifecycle._resolve_main = resolve_main
    job = importlib.import_module('one_job.job')
    job._same_root = _same_root
    host._darius_native_inspection = True


def failure_message(base_url, expected_root=None, *, reachable=False):
    """Useful local failure categories, without exposing command-line secrets."""
    endpoint = urlsplit(base_url)
    try:
        pid = listening_pid(endpoint.port or 80, endpoint.hostname)
        identity = process_identity(pid)
        if expected_root and not _same_root(identity.main.parent, expected_root):
            return 'The responding ComfyUI belongs to a different installation than the selected folder. Use Detect ComfyUI and save the detected folder.'
        return 'The ComfyUI process changed during verification. Check again after it finishes starting.'
    except InspectionError as error:
        messages = {
            'permission_denied': 'Windows is blocking access to the ComfyUI process. Close ComfyUI and start it normally under the same Windows account as Darius; avoid running only one app as administrator. Then Detect again.',
            'multiple_listeners': 'More than one process is listening at this address. Use http://127.0.0.1:8188 instead of localhost, or select the specific ComfyUI backend port.',
            'no_listener': ('ComfyUI responds over HTTP, but no matching local process could be identified. A proxy, container or WSL listener may be forwarding this port; use the native ComfyUI Python backend address.' if reachable else 'No local listener was found at the selected address. Start ComfyUI, wait for its ready message, then Detect again.'),
            'unrecognized_launcher': 'The listener is a launcher or proxy whose ComfyUI Python process could not be verified. Use the Python backend address, or launch ComfyUI through its normal Python startup script.',
            'working_folder_unavailable': 'ComfyUI uses a relative launch path, but Windows did not expose its working folder. Start ComfyUI under the same account and elevation as Darius.',
            'comfy_folder_unavailable': 'The process launch path does not resolve to an accessible ComfyUI folder. Check that its main.py and folder_paths.py are available.',
            'process_changed': 'ComfyUI restarted during inspection. Wait for it to finish starting, then check again.',
        }
        return messages.get(error.code, 'The local ComfyUI process could not be verified.')
    except (OSError, ValueError):
        return 'Windows could not complete ComfyUI process inspection. Start both applications under the same account and elevation, then check again.'
