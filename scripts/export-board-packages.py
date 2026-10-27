"""Author portable board setup contracts from reviewed templates and Block Party.

Reads the author ComfyUI/Block Party folders; writes only Darius setup metadata.
It never installs dependencies, modifies those folders or renders a workflow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, unquote, quote
import urllib.request

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api'))


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def git(directory, *arguments):
    return subprocess.check_output(['git', '-C', str(directory), *arguments], text=True, stderr=subprocess.DEVNULL).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--block-party', type=Path, required=True)
    parser.add_argument('--sources', type=Path, help='Additional reviewed folder/filename/url records (no credentials)')
    parser.add_argument('--profile', action='append', help='Export only the named profile; repeat for several profiles')
    args = parser.parse_args()
    sys.path.insert(0, str(args.block_party.resolve()))
    from one_job.export_job import build_manifest
    from one_job import slots
    # Dependency preparation recognizes the newer core sink. No graph rewriting
    # or Block Party source edits are needed; Darius remains the render owner.
    if 'SaveImageAdvanced' not in slots.IMAGE_SAVERS:
        slots.IMAGE_SAVERS += ('SaveImageAdvanced',)
    from one_job.host import find_model_file
    from one_job.slots import model_references
    from darius_api.config import Settings
    from darius_api.board_setup import profile_graph
    from darius_api.canvas_moss import digest

    settings = Settings.from_env()
    comfy = settings.block_party_comfy_root or settings.comfyui_output_dir.parent
    with urllib.request.urlopen(settings.comfyui_base_url.rstrip('/') + '/object_info', timeout=45) as response:
        schemas = json.load(response)
    sources = {}
    def remember(model):
        if model.get('folder') and model.get('filename'):
            sources.setdefault((model['folder'], model['filename']), []).append(model)
    for path in [*args.block_party.glob('jobs/*/manifest.json'), *ROOT.glob('workflows/canvas/*/source.manifest.json'), *ROOT.glob('workflows/board-setup/*.json')]:
        value = json.loads(path.read_text(encoding='utf-8'))
        for model in value.get('manifest', value).get('models', []):
            remember(model)
    for path in ROOT.glob('workflows/canvas/*/source.ui.json'):
        for url in re.findall(r'https://(?:huggingface\.co|civitai\.com)/[^\s"\\)<>]+', path.read_text(encoding='utf-8')):
            pieces = unquote(urlsplit(url).path).split('/')
            if pieces[-1].endswith(('.safetensors', '.gguf', '.pth', '.pt')):
                remember({'folder': pieces[-2], 'filename': pieces[-1], 'url': url})
    if args.sources:
        for model in json.loads(args.sources.read_text(encoding='utf-8')):
            remember(model)

    cache = {}
    def remote(url):
        parts = urlsplit(url)
        pieces = parts.path.strip('/').split('/')
        if parts.hostname != 'huggingface.co' or len(pieces) < 5 or pieces[2] not in {'resolve', 'blob'}:
            return None
        repo, revision, filename = '/'.join(pieces[:2]), pieces[3], unquote('/'.join(pieces[4:]))
        key = (repo, revision)
        if key not in cache:
            try:
                with urllib.request.urlopen(f'https://huggingface.co/api/models/{repo}/revision/{quote(revision, safe="")}?blobs=true', timeout=45) as response:
                    cache[key] = json.load(response)
            except OSError:
                cache[key] = {}
        metadata = cache[key]
        item = next((item for item in metadata.get('siblings', []) if item['rfilename'] == filename), {})
        hashed = item.get('lfs', {}).get('sha256')
        if not hashed:
            return None
        return {'url': f'https://huggingface.co/{repo}/resolve/{metadata["sha"]}/{quote(filename, safe="/")}',
                'sha256': hashed, 'size_bytes': item.get('size') or item.get('lfs', {}).get('size'),
                'auth': 'huggingface' if metadata.get('gated') else None}

    output = ROOT / 'workflows/board-setup'
    output.mkdir(exist_ok=True)
    for directory in sorted((ROOT / 'workflows/canvas').iterdir()):
        profile = directory.name
        if args.profile and profile not in args.profile:
            continue
        graph = profile_graph(settings, profile)
        selected = []
        hashes = {}
        for ref in model_references(graph):
            key = ref['folder'], ref['filename']
            choices = sources.get(key, [])
            known = {item['sha256'] for item in choices if item.get('sha256')}
            if len(known) > 1:
                raise ValueError(f'Conflicting author hashes for {key}')
            expected = next(iter(known), None)
            chosen = None
            for candidate in choices:
                if not candidate.get('url'):
                    continue
                metadata = remote(candidate['url'])
                if metadata and (not expected or metadata['sha256'] == expected):
                    chosen = {**candidate, **metadata}
                    break
                if candidate.get('sha256') and not metadata:
                    chosen = candidate
                    break
            model_path = find_model_file(comfy, *key)
            if not model_path:
                raise ValueError(f'Author model is not installed: {key}')
            if chosen:
                expected = chosen['sha256']
            elif not expected:
                print(f'Hashing {key[1]} (no publisher metadata)', flush=True)
                with model_path.open('rb') as stream:
                    expected = hashlib.file_digest(stream, 'sha256').hexdigest()
            hashes[str(model_path)] = expected
            selected.append({'folder': key[0], 'filename': key[1], 'url': chosen.get('url') if chosen else None,
                             'auth': chosen.get('auth') if chosen else None, 'size_bytes': model_path.stat().st_size})
        def resolve_model(filename, folder):
            path = find_model_file(comfy, folder, filename)
            return (folder, path) if path else None
        def resolve_pack(kind):
            module = schemas.get(kind, {}).get('python_module', '')
            if not module.startswith('custom_nodes.'):
                if not module:
                    raise ValueError(f'Author ComfyUI has not loaded {kind}')
                return None
            name = module.split('.')[1]
            path = comfy / 'custom_nodes' / name
            url = git(path, 'config', '--get', 'remote.origin.url')
            return {'name': name, 'git_url': url, 'commit': git(path, 'rev-parse', 'HEAD')}
        manifest = build_manifest(graph, resolve_model, resolve_pack, hash_file=lambda path: hashes[str(path)],
                                  name=profile, parameters=[], model_sources=selected)
        spec = {'schemaVersion': 1, 'profile': profile, 'graphDigest': digest(graph), 'manifest': manifest}
        (output / (profile + '.json')).write_text(json.dumps(spec, indent=2) + '\n', encoding='utf-8')
        missing = [item['filename'] for item in manifest['models'] if not item.get('url')]
        print(f'{profile}: {len(manifest["models"])} models, {len(manifest["nodes"])} node packs, missing sources: {missing}', flush=True)


if __name__ == '__main__':
    main()
