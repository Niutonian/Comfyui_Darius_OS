import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from darius_api.comfy_preflight import validate_graph
from darius_api.providers import ComfyMcpProvider, ProviderError, comfy_error_detail
from darius_api.workflows import WorkflowRegistry
from test_media_backend import settings_for


def test_comfy_subprocess_forces_utf8_for_unicode_workflow_envelopes(tmp_path, monkeypatch):
    prompt = "An angel in a café — 舞台"
    def run(command, **kwargs):
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        assert kwargs["env"]["PYTHONUTF8"] == "1"
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
            "type": "envelope", "ok": True, "data": {"prompt": prompt}}, ensure_ascii=False))
    monkeypatch.setattr("darius_api.providers.subprocess.run", run)
    assert ComfyMcpProvider(settings_for(tmp_path))._run(["--json", "run", "--print-prompt"], 10)["data"]["prompt"] == prompt


def test_reference_probe_retries_transient_failure(monkeypatch):
    calls = []
    def probe(url, timeout):
        calls.append(url)
        if len(calls) < 3:
            raise TimeoutError()
        return io.BytesIO(b'image')
    monkeypatch.setattr('urllib.request.urlopen', probe)
    monkeypatch.setattr('darius_api.comfy_preflight.time.sleep', lambda _: None)
    graph = {'1': {'class_type': 'LoadImage', 'inputs': {'image': 'reference.png'}}}
    assert validate_graph(graph, comfy_base_url='http://127.0.0.1:8188') == graph
    assert len(calls) == 3


def test_missing_reference_is_not_retried(monkeypatch):
    calls = []
    def probe(url, timeout):
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, 'missing', {}, io.BytesIO())
    monkeypatch.setattr('urllib.request.urlopen', probe)
    with pytest.raises(ProviderError, match='HTTP 404.*upload and bind'):
        validate_graph({'1': {'class_type': 'LoadImage', 'inputs': {'image': 'reference.png'}}},
                       comfy_base_url='http://127.0.0.1:8188')
    assert len(calls) == 1


def test_node_validation_details_are_preserved_without_tensor_payload():
    detail = comfy_error_detail({'message': 'Workflow rejected', 'details': {'node_errors': {
        '137': {'class_type': 'LoadImage', 'errors': [{'details': 'Invalid image file: reference.png'}]},
    }, 'large_tensor': [0] * 10000}})
    assert 'LoadImage 137: Invalid image file: reference.png' in detail
    assert len(detail) < 200


@pytest.mark.parametrize('invalid', [False, True])
@pytest.mark.parametrize('manual', [False, True])
def test_api_graph_execution_uses_verified_submission_only_after_validation(tmp_path, monkeypatch, invalid, manual):
    settings = settings_for(tmp_path)
    registry = WorkflowRegistry(settings.workflow_definitions_dir)
    registry.load()
    contract = registry.get('qwen-image-2-1-text-to-image')
    provider = ComfyMcpProvider(settings)
    monkeypatch.setattr(provider, 'validate_api_graph', lambda *a, **k: {
        'valid': not invalid, 'errors': ['missing model'] if invalid else [],
        'qwen_zero_reference_compatibility': True,
    })
    calls = []
    def submit(contract, graph, *, manual_approval=False):
        assert manual_approval is manual
        calls.append(graph)
        return {'data': {'prompt_id': 'test-prompt'}}
    monkeypatch.setattr(provider, '_submit_verified_local_graph', submit)
    monkeypatch.setattr(provider, '_run', lambda *a, **k: pytest.fail('CLI must not run an API graph'))
    monkeypatch.setattr(provider, '_history', lambda *a: {'status': {'completed': True}})
    monkeypatch.setattr(provider, '_collect', lambda *a: (tmp_path / 'output.png',))
    if invalid:
        with pytest.raises(ProviderError, match='missing model'):
            provider.execute(contract, contract.validate_inputs({'prompt': 'test'}), 'project', 'job', manual_approval=manual)
        assert calls == []
    else:
        result = provider.execute(contract, contract.validate_inputs({'prompt': 'test'}), 'project', 'job', manual_approval=manual)
        assert result.external_job_id == 'test-prompt'
        assert len(calls) == 1


def test_compatibility_submission_rejects_custom_nodes_before_network(tmp_path, monkeypatch):
    provider = ComfyMcpProvider(settings_for(tmp_path))
    contract = SimpleNamespace(execution_provider='local-comfyui', enabled=True,
                               runtime_mapping=SimpleNamespace(api_format=True), estimated_cost=0)
    monkeypatch.setattr('urllib.request.build_opener', lambda *a: pytest.fail('Must not submit custom nodes'))
    with pytest.raises(ProviderError, match='unverified or external'):
        provider._submit_verified_local_graph(contract, {'1': {'class_type': 'CustomPaidNode', 'inputs': {}}})


def test_submission_timeout_is_not_retried(tmp_path, monkeypatch):
    provider = ComfyMcpProvider(settings_for(tmp_path))
    monkeypatch.setattr('darius_api.local_render.verify_local_graph', lambda *a: None)
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            raise TimeoutError()
    monkeypatch.setattr('urllib.request.build_opener', lambda *a: Opener())
    with pytest.raises(ProviderError, match='check its queue before retrying'):
        provider._submit_verified_local_graph(None, {})
    assert len(calls) == 1


def test_manually_approved_custom_graph_can_submit(tmp_path, monkeypatch):
    provider = ComfyMcpProvider(settings_for(tmp_path))
    graph = {'1': {'class_type': 'H3Keyframes', 'inputs': {}}}
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(json.loads(request.data))
            return io.BytesIO(b'{"prompt_id":"reviewed-h3"}')
    monkeypatch.setattr('urllib.request.build_opener', lambda *a: Opener())
    result = provider._submit_verified_local_graph(None, graph, manual_approval=True)
    assert result['data']['prompt_id'] == 'reviewed-h3'
    assert calls == [{'prompt': graph}]


def test_qwen_zero_based_image_aliases_are_repaired_from_live_schema(tmp_path, monkeypatch):
    provider = ComfyMcpProvider(settings_for(tmp_path))
    graph = {'6': {'class_type': 'TextEncodeQwenImage21', 'inputs': {
        'images.image1': ['5', 0], 'images.image0': ['4', 0], 'prompt': 'test'}}}
    schema = {'TextEncodeQwenImage21': {'input': {'required': {
        'images': ['COMFY_AUTOGROW_V3', {'template': {'names': ['image_1', 'image_2'], 'min': 0}}]}}}}
    monkeypatch.setattr(provider, 'live_node_schemas', lambda graph: schema)
    monkeypatch.setattr(provider, '_run', lambda *a, **k: {'data': {'valid': True}})
    monkeypatch.setattr('darius_api.providers.accept_zero_reference_qwen_warning', lambda v, *a, **k: v)
    path = tmp_path / 'graph.json'
    path.write_text(json.dumps(graph))
    result = provider.validate_api_graph(path, graph, 10)
    assert result['valid'] is True
    assert result['input_repairs']
    assert graph['6']['inputs'] == {'prompt': 'test', 'images.image_1': ['4', 0], 'images.image_2': ['5', 0]}
    assert json.loads(path.read_text()) == graph


@pytest.mark.parametrize('slots', [
    {'images.image0': ['4', 0], 'images.image_1': ['5', 0]},
    {'images.image1': ['4', 0]},
    {'images.guessed': ['4', 0]},
])
def test_ambiguous_dynamic_image_names_fail_before_submission(slots):
    from darius_api.comfy_preflight import normalize_dynamic_inputs
    graph = {'6': {'class_type': 'TextEncodeQwenImage21', 'inputs': slots.copy()}}
    schema = {'TextEncodeQwenImage21': {'input': {'required': {
        'images': ['COMFY_AUTOGROW_V3', {'template': {'names': ['image_1', 'image_2']}}]}}}}
    with pytest.raises(ProviderError, match='unsupported dynamic inputs.*images.image_1'):
        normalize_dynamic_inputs(graph, schema)
    assert graph['6']['inputs'] == slots


def test_server_rejection_preserves_node_details(tmp_path, monkeypatch):
    provider = ComfyMcpProvider(settings_for(tmp_path))
    monkeypatch.setattr('darius_api.local_render.verify_local_graph', lambda *a: None)
    class Opener:
        def open(self, request, timeout):
            body = {'node_errors': {'8': {'class_type': 'KSampler', 'errors': [{'details': 'invalid sampler'}]}}}
            raise urllib.error.HTTPError(request.full_url, 400, 'rejected', {}, io.BytesIO(json.dumps(body).encode()))
    monkeypatch.setattr('urllib.request.build_opener', lambda *a: Opener())
    with pytest.raises(ProviderError, match='KSampler 8: invalid sampler'):
        provider._submit_verified_local_graph(None, {})


def test_draft_with_unavailable_reference_is_not_registered(tmp_path, monkeypatch):
    from darius_api.comfy_assistant import ComfyAssistantTools
    def missing(*args):
        raise ProviderError('Reference unavailable')
    monkeypatch.setattr('darius_api.comfy_preflight._visible_in_comfy', missing)
    monkeypatch.setattr(ComfyMcpProvider, '_run', lambda *a, **k: pytest.fail('Reject before MCP validation'))
    tools = ComfyAssistantTools(settings_for(tmp_path), None, None)
    graph = {'1': {'class_type': 'LoadImage', 'inputs': {'image': 'missing.png'}},
             '2': {'class_type': 'SaveImage', 'inputs': {'images': ['1', 0], 'filename_prefix': 'test'}}}
    result = tools.call({'operation': 'validate_graph', 'arguments_json': json.dumps({'graph': graph})})
    assert result['error'] == 'Reference unavailable'
