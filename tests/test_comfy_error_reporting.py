import json
from types import SimpleNamespace

import pytest
from darius_api.providers import ComfyMcpProvider, ProviderError
from test_media_backend import settings_for


def test_failed_process_surfaces_structured_error_instead_of_tensor_dump(tmp_path, monkeypatch):
    envelope = {"type": "envelope", "ok": False, "error": {"message": "H3Keyframes (node 8): incompatible positional patch", "details": {"large_tensor": [0] * 2000}}}
    monkeypatch.setattr("subprocess.run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="tensor dump\n" + json.dumps(envelope), stderr="progress log"))
    with pytest.raises(ProviderError) as error:
        ComfyMcpProvider(settings_for(tmp_path))._run(["run"], 5)
    assert str(error.value) == "Comfy MCP failed: H3Keyframes (node 8): incompatible positional patch"
