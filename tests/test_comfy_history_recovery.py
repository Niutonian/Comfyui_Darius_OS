import io
import json
from types import SimpleNamespace

import pytest

from darius_api import providers, job_recovery


def poll(monkeypatch, payloads, idle):
    clock = [0]
    monkeypatch.setattr(providers.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(providers.time, 'sleep', lambda _: clock.__setitem__(0, clock[0] + 10))
    monkeypatch.setattr(providers.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps(next(payloads)).encode()))
    monkeypatch.setattr(job_recovery, 'comfy_queue_idle', lambda _: next(idle))
    return providers.ComfyMcpProvider(SimpleNamespace(comfy_job_timeout_seconds=120, comfyui_base_url='http://127.0.0.1:8188'))


def test_missing_prompt_and_repeated_idle_queue_release_worker(monkeypatch):
    provider = poll(monkeypatch, iter([{}] * 6), iter([True] * 3))
    with pytest.raises(providers.ProviderError, match='no render was resubmitted'):
        provider._history('lost')


def test_busy_or_unknown_queue_resets_missing_prompt_check(monkeypatch):
    result = {'status': {'completed': True}, 'outputs': {}}
    provider = poll(monkeypatch, iter([{}] * 7 + [{'present': result}]), iter([True, True, False, True]))
    assert provider._history('present') == result


def test_history_result_wins_before_idle_detection(monkeypatch):
    result = {'status': {'completed': False, 'status_str': 'error'}}
    provider = poll(monkeypatch, iter([{'present': result}]), iter([]))
    assert provider._history('present') == result


def test_sequential_wait_extends_only_while_its_prompt_is_queued(monkeypatch):
    result = {'status': {'completed': True}}
    provider = poll(monkeypatch, iter([{}, {}, {}, {'present': result}]), iter([False]))
    checked=[]
    monkeypatch.setattr(provider, '_prompt_queued', lambda key: checked.append(key) or True)
    assert provider._history('present', 20, keep_alive_while_busy=True) == result
    assert checked == ['present']


def test_sequential_timeout_does_not_extend_for_another_or_unknown_prompt(monkeypatch):
    provider = poll(monkeypatch, iter([{}, {}]), iter([]))
    monkeypatch.setattr(provider, '_prompt_queued', lambda key: False)
    with pytest.raises(providers.ProviderError, match='history did not contain'):
        provider._history('missing', 20, keep_alive_while_busy=True)


@pytest.mark.parametrize('queue,expected', [
    ({'queue_running':[[0,'mine']], 'queue_pending':[]},True),
    ({'queue_running':[], 'queue_pending':[[1,'mine']]},True),
    ({'queue_running':[[0,'other']], 'queue_pending':[]},False),
    ({'queue_running':[], 'queue_pending':[]},False),
    ({'queue_running':[], 'queue_pending':None},False),
])
def test_long_run_queue_probe_is_prompt_specific(monkeypatch,queue,expected):
    provider = providers.ComfyMcpProvider(SimpleNamespace(comfyui_base_url='http://127.0.0.1:8188'))
    monkeypatch.setattr(providers.urllib.request,'urlopen',lambda *a,**kw:io.BytesIO(json.dumps(queue).encode()))
    assert provider._prompt_queued('mine') is expected
