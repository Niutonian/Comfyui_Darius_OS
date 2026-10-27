"""Narrow, source-verified reuse of FIBO's existing KJ string nodes.

This adapts Darius-owned preparation contracts, never installed node packs or
received ZIPs. Block Party still verifies the actual revision and fingerprints.
"""
import ast
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re
import subprocess

PIN = 'd3cfe21625e5170126ce06fbfcfe1d88108688c3'
ORIGIN = 'https://github.com/kijai/comfyui-kjnodes'
# AST fingerprints reviewed from PIN:nodes/nodes.py. Only presentation labels
# are excluded; schema methods, execution methods and return types are included.
SIGNATURES = {
    'StringConstantMultiline': '2303c5a90363699ddf535b8e8acc2bb7ad26d2b53c74af9b252e14ccdd0fe756',
    'JoinStrings': 'e5daef0b24cae5454c895a0142320ae91d0d2d71c297d5e3e5e7244eeb71d747',
    'SomethingToString': '3f0215bcfa8ba4f504dae3916aad04708f4218135f435e60c7decfde355d1c55',
}


def git(pack, *args):
    result = subprocess.run(['git', '--no-optional-locks', '-C', str(pack), *args],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('Node checkout could not be inspected')
    return result.stdout.strip()


def class_signatures(source):
    tree = ast.parse(source)
    result = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in SIGNATURES:
            continue
        if node.name in result:
            raise ValueError('Duplicate node class')
        node.body = [part for part in node.body if not (
            isinstance(part, ast.Assign) and all(isinstance(t, ast.Name) and
                t.id in {'CATEGORY', 'DESCRIPTION', 'SEARCH_ALIASES'} for t in part.targets))]
        result[node.name] = sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
    # SomethingToString's only non-builtin dependency must retain its binding.
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)
        and node.module == 'comfy.comfy_types.node_typing'
        and any(name.name == 'IO' and name.asname in {None, 'IO'} for name in node.names)]
    if not imports:
        raise ValueError('Node typing import changed')
    return result


def reuse_installed(profile, manifest, link):
    """Re-pin only known identical nodes, otherwise retain normal conflict checks."""
    if profile not in {'fibo-fast-turbo-v2', 'fibo-fast-experimental-v1', 'fibo-dev-v1'}:
        return manifest, []
    adapted, reused = deepcopy(manifest), []
    for node in adapted.get('nodes', []):
        if (node.get('name') != 'comfyui-kjnodes' or node.get('commit') != PIN
                or node.get('git_url', '').lower().removesuffix('.git') != ORIGIN
                or set(node.get('class_types', [])) != set(SIGNATURES)):
            continue
        pack = Path(link.custom_nodes) / node['name']
        if not pack.is_dir():
            continue
        try:
            # No external/symlinked tree, unrelated origin, local modifications
            # or source substitutions qualify for automatic reuse.
            if pack.is_symlink() or not pack.resolve().is_relative_to(Path(link.custom_nodes).resolve()):
                continue
            if Path(git(pack, 'rev-parse', '--show-toplevel')).resolve() != pack.resolve():
                continue
            actual = git(pack, 'rev-parse', 'HEAD')
            if actual == PIN or not re.fullmatch('[0-9a-f]{40}', actual):
                continue
            if git(pack, 'config', '--get', 'remote.origin.url').lower().removesuffix('.git').rstrip('/') != ORIGIN:
                continue
            if git(pack, 'status', '--porcelain', '--untracked-files=normal'):
                continue
            path = pack / 'nodes' / 'nodes.py'
            if not path.resolve().is_relative_to(pack.resolve()) or path.stat().st_size > 2_000_000:
                continue
            raw = path.read_bytes()
            if class_signatures(raw.decode('utf-8-sig')) != SIGNATURES:
                continue
            from one_job.comfy import _request
            import json
            registry = json.loads(_request(link.url.rstrip('/') + '/object_info')[1])
            # ComfyUI folder casing may differ on Windows.
            if any(registry.get(kind, {}).get('python_module', '').lower().split('.')[:2] !=
                   ['custom_nodes', node['name']] for kind in SIGNATURES):
                continue
            node['commit'] = actual
            reused.append({'name': node['name'], 'bundledCommit': PIN, 'commit': actual,
                           'sourceSha256': sha256(raw).hexdigest()})
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return adapted, reused


def receipt_matches(root, receipts):
    """Invalidate readiness if a reused checkout changes after preparation."""
    try:
        for receipt in receipts:
            if receipt.get('name') != 'comfyui-kjnodes' or not root:
                return False
            pack = Path(root) / 'custom_nodes' / receipt['name']
            path = pack / 'nodes' / 'nodes.py'
            if (pack.is_symlink() or not pack.resolve().is_relative_to((Path(root) / 'custom_nodes').resolve())
                    or not path.resolve().is_relative_to(pack.resolve())
                    or git(pack, 'rev-parse', 'HEAD') != receipt['commit']
                    or git(pack, 'status', '--porcelain', '--untracked-files=normal')
                    or sha256(path.read_bytes()).hexdigest() != receipt['sourceSha256']):
                return False
        return True
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return False
