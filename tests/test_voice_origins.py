import json
import pytest
from apps.voice.origins import voice_origins


def test_only_configured_https_lan_origin_is_trusted(tmp_path):
    folder = tmp_path / "data/lan-https"; folder.mkdir(parents=True)
    (folder / "settings.json").write_text(json.dumps({"version": 1, "address": "192.168.50.10", "port": 3443}))
    origins = voice_origins(tmp_path)
    assert "https://192.168.50.10:3443" in origins
    assert "http://localhost:3000" in origins
    assert "https://192.168.0.165:3443" not in origins
    assert "https://untrusted.example" not in origins


@pytest.mark.parametrize("address", ["8.8.8.8", "example.com", "0.0.0.0", "127.0.0.1", "169.254.1.2", "224.0.0.1", "192.0.2.1", "192.168.50.10/path"])
def test_invalid_or_non_lan_gateway_cannot_widen_origins(tmp_path, address):
    folder = tmp_path / "data/lan-https"; folder.mkdir(parents=True)
    (folder / "settings.json").write_text(json.dumps({"version": 1, "address": address, "port": 3443}))
    assert not any(origin.startswith("https://") for origin in voice_origins(tmp_path))
