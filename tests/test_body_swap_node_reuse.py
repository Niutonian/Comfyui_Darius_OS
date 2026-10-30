import json
import sys
from pathlib import Path
from types import SimpleNamespace, ModuleType
from darius_api import board_node_reuse as reuse


def test_body_swap_local_sources_and_loaded_owner_are_required(tmp_path, monkeypatch):
    name='ComfyUI-Darius-Ollama';pack=tmp_path/'custom_nodes'/name;pack.mkdir(parents=True)
    (pack/'nodes.py').write_text('class Example: pass\n')
    expected=reuse.source_files(pack)
    manifest={'nodes':[{'name':name,'git_url':None,'commit':'a'*40,'class_types':['DariusOllamaModel','DariusOllamaH3SwapPrompt']}], 'local_source_pins':{name:expected}}
    registry={k:{'python_module':'custom_nodes.'+name+'.nodes'} for k in manifest['nodes'][0]['class_types']}
    module=ModuleType('one_job.comfy');module._request=lambda url:(200,json.dumps(registry).encode())
    monkeypatch.setitem(sys.modules,'one_job.comfy',module)
    link=SimpleNamespace(custom_nodes=pack.parent,url='http://localhost:8188')
    adapted,receipts=reuse.reuse_installed('minimax-h3-body-swap-v1',manifest,link)
    assert adapted['nodes']==[] and manifest['nodes']
    assert reuse.receipt_matches(tmp_path,receipts)
    (pack/'nodes.py').write_text('class Changed: pass\n')
    assert not reuse.receipt_matches(tmp_path,receipts)
    assert reuse.reuse_installed('minimax-h3-body-swap-v1',manifest,link)[1]==[]
    (pack/'nodes.py').write_text('class Example: pass\n')
    registry['DariusOllamaModel']['python_module']='custom_nodes.other.nodes'
    assert reuse.reuse_installed('minimax-h3-body-swap-v1',manifest,link)[1]==[]
    registry['DariusOllamaModel']['python_module']='custom_nodes.'+name+'.nodes'
    (pack/'extra.py').write_text('print("unreviewed")')
    assert reuse.reuse_installed('minimax-h3-body-swap-v1',manifest,link)[1]==[]


def test_local_preparation_keeps_contract_model_git_and_runtime_checks(tmp_path, monkeypatch):
    from darius_api import board_setup
    graph={'1':{'class_type':'Example','inputs':{}}};manifest={'nodes':[]};receipts=[{'scheme':'source-files-v1'}]
    (tmp_path/'workflow.api.json').write_text(json.dumps(graph))
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    calls=[]
    module=ModuleType('one_job.job')
    for name in ['check_contract','verify_nodes','verify_models','verify_registered_nodes']:
        setattr(module,name,lambda *args,name=name:calls.append(name))
    monkeypatch.setitem(sys.modules,'one_job.job',module)
    runtime=ModuleType('one_job.runtime_requirements');runtime.verify_runtime_requirements=lambda *args:calls.append('runtime')
    monkeypatch.setitem(sys.modules,'one_job.runtime_requirements',runtime)
    monkeypatch.setattr(reuse,'receipt_matches',lambda *args:True)
    monkeypatch.setattr(reuse,'reuse_body_swap',lambda *args:(manifest,receipts))
    link=SimpleNamespace(comfy_root=tmp_path,custom_nodes=tmp_path/'custom_nodes')
    board_setup._prepare_local_sources(tmp_path,link,graph,manifest,manifest,receipts)
    assert calls==['check_contract','verify_nodes','verify_models','verify_registered_nodes','runtime']
    (tmp_path/'workflow.api.json').write_text('{}')
    import pytest
    with pytest.raises(board_setup.SetupError,match='contract changed'):
        board_setup._prepare_local_sources(tmp_path,link,graph,manifest,manifest,receipts)


def test_sequential_local_pack_checks_loaded_ownership_and_exact_source(tmp_path,monkeypatch):
    name='ComfyUI-Darius-Recast';pack=tmp_path/'custom_nodes'/name;pack.mkdir(parents=True)
    (pack/'nodes.py').write_text('class Example: pass\n')
    kinds=['RecastH3Sequential','RecastH3VideoSize']
    manifest={'nodes':[{'name':name,'class_types':kinds}], 'local_source_pins':{name:reuse.source_files(pack)}}
    registry={k:{'python_module':'custom_nodes.'+name} for k in kinds}
    module=ModuleType('one_job.comfy');module._request=lambda url:(200,json.dumps(registry).encode())
    monkeypatch.setitem(sys.modules,'one_job.comfy',module)
    link=SimpleNamespace(custom_nodes=pack.parent,url='http://localhost:8188')
    adapted,receipts=reuse.reuse_installed('minimax-h3-body-swap-sequential-v1',manifest,link)
    assert adapted['nodes']==[] and reuse.receipt_matches(tmp_path,receipts)
    registry[kinds[0]]['python_module']='custom_nodes.other'
    assert reuse.reuse_installed('minimax-h3-body-swap-sequential-v1',manifest,link)[1]==[]
