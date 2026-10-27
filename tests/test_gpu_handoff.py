import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from darius_api.gpu_handoff import unload_idle_comfy, unload_ollama
from darius_api.providers import LlamaCppPlannerProvider, OllamaPlannerProvider


def install_opener(monkeypatch, queue):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            if isinstance(request, str):
                if isinstance(queue, Exception):
                    raise queue
                return io.BytesIO(json.dumps(queue).encode())
            return io.BytesIO(b"")

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    return calls


def test_comfy_idle_cache_only_is_released(monkeypatch):
    calls = install_opener(monkeypatch, {"queue_running": [], "queue_pending": []})
    unload_idle_comfy(SimpleNamespace(comfyui_base_url="http://127.0.0.1:8188"))
    assert calls[0].endswith("/queue")
    assert calls[1].full_url.endswith("/free")
    assert json.loads(calls[1].data) == {"unload_models": True, "free_memory": True}


@pytest.mark.parametrize("queue", [
    {"queue_running": [[1]], "queue_pending": []},
    {"queue_running": [], "queue_pending": [[1]]}, {}, [],
])
def test_busy_or_unknown_comfy_queue_never_mutated(monkeypatch, queue):
    calls = install_opener(monkeypatch, queue)
    with pytest.raises(RuntimeError):
        unload_idle_comfy(SimpleNamespace(comfyui_base_url="http://localhost:8188"))
    assert len(calls) == 1


def test_stopped_comfy_does_not_block_chat(monkeypatch):
    calls = install_opener(monkeypatch, urllib.error.URLError(ConnectionRefusedError()))
    unload_idle_comfy(SimpleNamespace(comfyui_base_url="http://127.0.0.1:8188"))
    assert len(calls) == 1


def test_unreachable_comfy_is_not_assumed_idle(monkeypatch):
    calls = install_opener(monkeypatch, urllib.error.URLError(TimeoutError()))
    with pytest.raises(RuntimeError, match="check ComfyUI"):
        unload_idle_comfy(SimpleNamespace(comfyui_base_url="http://127.0.0.1:8188"))
    assert len(calls) == 1


def test_remote_comfy_is_never_contacted(monkeypatch):
    calls = install_opener(monkeypatch, {})
    with pytest.raises(RuntimeError, match="loopback"):
        unload_idle_comfy(SimpleNamespace(comfyui_base_url="http://example.com:8188"))
    assert not calls


def test_handoff_respects_provider_specific_switches(monkeypatch):
    calls = []
    monkeypatch.setattr("darius_api.gpu_handoff.unload_idle_comfy", lambda settings: calls.append(settings))
    provider = object.__new__(LlamaCppPlannerProvider)
    provider.settings = SimpleNamespace(llamacpp_unload_idle_comfy=False)
    provider._prepare_gpu()
    assert not calls
    provider.settings.llamacpp_unload_idle_comfy = True
    provider._prepare_gpu()
    assert len(calls) == 1
    ollama = object.__new__(OllamaPlannerProvider)
    ollama.settings = provider.settings
    ollama.settings.ollama_unload_idle_comfy = False
    ollama._prepare_gpu()
    assert len(calls) == 1
    ollama.settings.ollama_unload_idle_comfy = True
    ollama._prepare_gpu()
    assert len(calls) == 2


def ollama_opener(monkeypatch, responses):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return io.BytesIO(json.dumps(value).encode())
    monkeypatch.setattr('urllib.request.build_opener', lambda *args: Opener())
    return calls


OLLAMA = SimpleNamespace(ollama_base_url='http://127.0.0.1:11434', ollama_model='not-installed:latest')


@pytest.mark.parametrize('models', [[], [{'name': 'cpu-model', 'size_vram': 0}]])
def test_no_gpu_resident_never_sends_generate_or_requires_configured_model(monkeypatch, models):
    calls = ollama_opener(monkeypatch, [{'models': models}])
    unload_ollama(OLLAMA)
    assert calls == [OLLAMA.ollama_base_url + '/api/ps']


def test_stopped_ollama_allows_render_but_unknown_connection_failure_does_not(monkeypatch):
    ollama_opener(monkeypatch, [urllib.error.URLError(ConnectionRefusedError())])
    unload_ollama(OLLAMA)
    ollama_opener(monkeypatch, [urllib.error.URLError(TimeoutError())])
    with pytest.raises(RuntimeError, match='checking running models'):
        unload_ollama(OLLAMA)


def test_exact_resident_names_are_unloaded_not_default_or_similar_tags(monkeypatch):
    calls = ollama_opener(monkeypatch, [
        {'models': [{'name': 'ornith:35b', 'size_vram': 100}, {'model': 'ornith:9b'},
                    {'name': 'cpu-model', 'size_vram': 0}]}, {}, {}, {'models': []}])
    unload_ollama(OLLAMA)
    payloads = [json.loads(call.data) for call in calls if not isinstance(call, str)]
    assert {item['model'] for item in payloads} == {'ornith:35b', 'ornith:9b'}
    assert all(item['keep_alive'] == 0 and 'prompt' not in item for item in payloads)
    assert len(calls) == 4


@pytest.mark.parametrize('data', [{}, [], {'models': None}, {'models': [None]},
                                  {'models': [{'name': 'm', 'size_vram': '0'}]}])
def test_invalid_residency_is_not_assumed_empty(monkeypatch, data):
    calls = ollama_opener(monkeypatch, [data])
    with pytest.raises(RuntimeError, match='checking running models'):
        unload_ollama(OLLAMA)
    assert len(calls) == 1


@pytest.mark.parametrize('status', [401, 404, 500])
def test_ollama_http_failure_reports_status_without_leaking_body(monkeypatch, status):
    error = urllib.error.HTTPError('http://local/api/ps', status, 'secret-body', {}, None)
    ollama_opener(monkeypatch, [error])
    with pytest.raises(RuntimeError, match=f'HTTP {status}') as failure:
        unload_ollama(OLLAMA)
    assert 'secret-body' not in str(failure.value)


def test_unload_404_requires_residency_proof(monkeypatch):
    missing = lambda: urllib.error.HTTPError('http://local/api/generate', 404, 'missing', {}, None)
    resident = {'models': [{'name': 'running:tag', 'size_vram': 20}]}
    ollama_opener(monkeypatch, [resident, missing(), {'models': []}, {'models': []}])
    unload_ollama(OLLAMA)
    ollama_opener(monkeypatch, [resident, missing(), resident])
    with pytest.raises(RuntimeError, match='HTTP 404'):
        unload_ollama(OLLAMA)


def test_new_resident_after_unload_still_blocks_comfy(monkeypatch):
    ollama_opener(monkeypatch, [{'models': [{'name': 'running', 'size_vram': 20}]}, {},
                              {'models': [{'name': 'other-model', 'size_vram': 20}]}])
    monkeypatch.setattr('darius_api.gpu_handoff.time.sleep', lambda _: None)
    times = iter([0, 0, 0, 31])
    monkeypatch.setattr('darius_api.gpu_handoff.time.monotonic', lambda: next(times))
    with pytest.raises(RuntimeError, match='still reports GPU-resident'):
        unload_ollama(OLLAMA)
