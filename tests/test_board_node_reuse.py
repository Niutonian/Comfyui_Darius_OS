"""Equivalent installed nodes may be reused; installer pins remain exact."""
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest

from darius_api import board_node_reuse as reuse


SOURCE = '''from comfy.comfy_types.node_typing import IO
class Example:
    CATEGORY = "label"
    @classmethod
    def INPUT_TYPES(cls): return {"required": {"text": ("STRING",)}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "run"
    def run(self, text): return (text,)
'''


@pytest.fixture
def installed(tmp_path, monkeypatch):
    monkeypatch.setattr(reuse, 'SIGNATURES', {'Example': ''})
    signatures = reuse.class_signatures(SOURCE)
    monkeypatch.setattr(reuse, 'SIGNATURES', signatures)
    pack = tmp_path / 'custom_nodes' / 'comfyui-kjnodes'
    (pack / 'nodes').mkdir(parents=True)
    (pack / 'nodes' / 'nodes.py').write_text(SOURCE)
    state = {'HEAD': 'a' * 40, 'dirty': '', 'origin': reuse.ORIGIN}
    def git(path, *args):
        assert Path(path) == pack
        if args == ('rev-parse', '--show-toplevel'): return str(pack)
        if args == ('rev-parse', 'HEAD'): return state['HEAD']
        if args[0] == 'status': return state['dirty']
        if args[0] == 'config': return state['origin']
        raise AssertionError(args)
    monkeypatch.setattr(reuse, 'git', git)
    registry = {'Example': {'python_module': 'custom_nodes.ComfyUI-KJNodes.nodes'}}
    comfy = ModuleType('one_job.comfy')
    comfy._request = lambda url: (200, json.dumps(registry).encode())
    monkeypatch.setitem(sys.modules, 'one_job.comfy', comfy)
    manifest = {'nodes': [{'name': 'comfyui-kjnodes', 'commit': reuse.PIN,
        'git_url': 'https://github.com/kijai/ComfyUI-KJNodes', 'class_types': ['Example']}]}
    link = SimpleNamespace(custom_nodes=pack.parent, url='http://127.0.0.1:8188')
    return pack, state, manifest, link, registry


def test_source_equivalence_repins_only_preparation_contract_and_records_receipt(installed):
    pack, state, original, link, _ = installed
    before = (pack / 'nodes/nodes.py').read_bytes()
    adapted, receipts = reuse.reuse_installed('fibo-fast-turbo-v2', original, link)
    assert original['nodes'][0]['commit'] == reuse.PIN
    assert adapted['nodes'][0]['commit'] == state['HEAD']
    assert receipts[0]['bundledCommit'] == reuse.PIN
    assert reuse.receipt_matches(pack.parent.parent, receipts)
    assert (pack / 'nodes/nodes.py').read_bytes() == before
    state['HEAD'] = 'b' * 40
    assert not reuse.receipt_matches(pack.parent.parent, receipts)


@pytest.mark.parametrize('change', ['dirty', 'origin', 'behavior', 'schema', 'owner', 'missing', 'profile', 'pin', 'classes', 'import'])
def test_unverified_changes_keep_original_pin_and_cannot_bypass_conflict(installed, change):
    pack, state, manifest, link, registry = installed
    profile = 'fibo-fast-turbo-v2'
    if change == 'dirty': state['dirty'] = ' M nodes/nodes.py'
    if change == 'origin': state['origin'] = 'https://github.com/other/repo'
    if change == 'behavior': (pack / 'nodes/nodes.py').write_text(SOURCE.replace('return (text,)', 'return ("changed",)'))
    if change == 'schema': (pack / 'nodes/nodes.py').write_text(SOURCE.replace('"STRING"', '"INT"'))
    if change == 'owner': registry['Example']['python_module'] = 'custom_nodes.another_pack'
    if change == 'missing': registry.clear()
    if change == 'profile': profile = 'untrusted-import'
    if change == 'pin': manifest['nodes'][0]['commit'] = 'b' * 40
    if change == 'classes': manifest['nodes'][0]['class_types'].append('Unknown')
    if change == 'import': (pack / 'nodes/nodes.py').write_text(SOURCE.replace('node_typing', 'other'))
    adapted, receipts = reuse.reuse_installed(profile, manifest, link)
    assert adapted == manifest and not receipts


def test_ui_labels_and_formatting_do_not_change_execution_signature(installed):
    expected = reuse.class_signatures(SOURCE)
    assert reuse.class_signatures(SOURCE.replace('"label"', '"new label"').replace('return (text,)', 'return ( text, )')) == expected


def test_reused_source_or_dirty_tree_invalidates_readiness(installed):
    pack, state, manifest, link, _ = installed
    _, receipts = reuse.reuse_installed('fibo-dev-v1', manifest, link)
    state['dirty'] = '?? extra.py'
    assert not reuse.receipt_matches(pack.parent.parent, receipts)
    state['dirty'] = ''
    (pack / 'nodes/nodes.py').write_text(SOURCE + '\n# changed\n')
    assert not reuse.receipt_matches(pack.parent.parent, receipts)
