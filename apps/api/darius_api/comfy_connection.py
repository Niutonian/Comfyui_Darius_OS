"""Machine-local ComfyUI connection, shared by the API and future workers."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
from urllib.parse import urlsplit

from .atomic_files import atomic_json


def local_url(value):
    if not isinstance(value, str):
        raise ValueError('ComfyUI server address must be text.')
    target = urlsplit(value.strip())
    if (target.scheme != 'http' or target.hostname not in {'localhost', '127.0.0.1', '::1'}
            or target.username or target.password or target.query or target.fragment or target.path not in {'', '/'}):
        raise ValueError('Use this server’s local ComfyUI address, for example http://127.0.0.1:8188.')
    if target.port is not None and not 1 <= target.port <= 65535:
        raise ValueError('ComfyUI port must be between 1 and 65535.')
    return value.strip().rstrip('/')


def connection_file(settings):
    return settings.data_dir / 'machine' / 'comfyui.json'


def cli_path(settings):
    current = getattr(settings, 'comfy_mcp_command', 'comfy')
    if Path(current).is_file() or (current not in {'comfy', 'comfy.exe'} and shutil.which(current)):
        return current
    roots = [settings.data_dir]
    if getattr(settings, 'repository_root', None):
        roots.append(settings.repository_root / 'data')
    for directory in roots:
        root = directory / 'tools' / 'comfy-cli' / '1.17.0' / 'venv'
        for relative in ('Scripts/comfy.exe', 'bin/comfy'):
            if (root / relative).is_file():
                return str(root / relative)
    return shutil.which(current) or shutil.which('comfy') or current


def effective_settings(settings):
    if not getattr(settings, 'data_dir', None):
        return settings
    updates = {}
    try:
        value = json.loads(connection_file(settings).read_text(encoding='utf-8'))
        root = Path(value['root']).resolve()
        if not (root / 'main.py').is_file() or not (root / 'folder_paths.py').is_file():
            raise ValueError('Saved ComfyUI folder is unavailable')
        updates = {'block_party_comfy_root': root, 'comfyui_base_url': local_url(value['baseUrl']),
                   'comfyui_output_dir': Path(value.get('outputDir') or root / 'output').resolve(),
                   'comfy_workflow_root': root / 'user' / 'default' / 'workflows'}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    command = cli_path(settings)
    if hasattr(settings, 'comfy_mcp_command') and command != settings.comfy_mcp_command:
        updates['comfy_mcp_command'] = command
    return replace(settings, **updates) if updates else settings


def describe(settings):
    current = effective_settings(settings)
    root = current.block_party_comfy_root
    if not root and current.comfyui_output_dir:
        root = current.comfyui_output_dir.parent
    valid = bool(root and (root / 'main.py').is_file() and (root / 'folder_paths.py').is_file())
    return {'root': str(root) if valid else '', 'baseUrl': current.comfyui_base_url,
            'outputDir': str(current.comfyui_output_dir) if valid and current.comfyui_output_dir else '',
            'configured': valid, 'saved': connection_file(settings).is_file(),
            'cliReady': bool(Path(current.comfy_mcp_command).is_file() or shutil.which(current.comfy_mcp_command))}


def save(settings, root, base_url, *, output_dir=None):
    root = root.strip()
    if len(root) > 1 and root[0] == root[-1] and root[0] in {'"', "'"}:
        root = root[1:-1]
    root = Path(root).expanduser().resolve()
    if not (root / 'main.py').is_file() and (root / 'ComfyUI' / 'main.py').is_file():
        root = root / 'ComfyUI'
    if not (root / 'main.py').is_file() or not (root / 'folder_paths.py').is_file():
        raise ValueError('Choose the ComfyUI folder containing main.py and folder_paths.py, or its portable-install parent folder.')
    output = root / 'output'
    if output_dir:
        output = Path(output_dir.strip().strip('"')).expanduser().resolve()
        if not output.is_dir():
            raise ValueError('Choose an existing custom output folder, or leave it blank for ComfyUI’s default.')
    value = {'root': str(root), 'baseUrl': local_url(base_url), 'outputDir': str(output)}
    atomic_json(connection_file(settings), value)
    return describe(settings)


def detect(settings, base_url=None):
    from . import board_setup
    base_url = local_url(base_url or effective_settings(settings).comfyui_base_url)
    board_setup.runtime(settings, lambda event: None)
    from one_job.host import link_from_running_server
    target = urlsplit(base_url)
    link = link_from_running_server(target.port or 80, target.hostname)
    if link is None:
        from .comfy_host import failure_message
        from one_job.host import server_is_comfy
        raise ValueError(failure_message(base_url, reachable=server_is_comfy(base_url)))
    root = Path(link.comfy_root).resolve()
    if not (root / 'main.py').is_file() or not (root / 'folder_paths.py').is_file():
        raise ValueError('The running process did not identify a usable ComfyUI folder. Enter its folder below.')
    output = link.comfy_output
    # Preserve an absolute custom output folder reported by the verified server.
    # Never expose or persist its full launch arguments.
    try:
        from one_job.comfy import _request
        arguments = json.loads(_request(base_url + '/system_stats')[1]).get('system', {}).get('argv', [])
        for index, argument in enumerate(arguments):
            value = arguments[index + 1] if argument == '--output-directory' and index + 1 < len(arguments) else argument.partition('=')[2] if isinstance(argument, str) and argument.startswith('--output-directory=') else ''
            if value and Path(value).is_absolute():
                output = str(Path(value).resolve())
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return {'root': str(root), 'baseUrl': base_url, 'configured': True, 'outputDir': output}
