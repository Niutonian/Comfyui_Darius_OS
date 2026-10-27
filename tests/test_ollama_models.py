from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest

from darius_api import ollama_models
from darius_api.main import create_app
from darius_api.providers import OllamaPlannerProvider, ProviderError
from test_media_backend import settings_for


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr(ollama_models, "_cache", ("", 0.0, ()))
    monkeypatch.setattr(ollama_models, "_failure", ("", 0.0))
    opener = MagicMock()
    response = opener.open.return_value.__enter__.return_value
    response.read.return_value = b'{"models":[{"name":"qwen-local:latest"}]}'
    build = MagicMock(return_value=opener)
    monkeypatch.setattr(ollama_models.urllib.request, "build_opener", build)
    return SimpleNamespace(
        settings=SimpleNamespace(ollama_base_url="http://127.0.0.1:11434/", ollama_model="default:latest"),
        opener=opener, response=response, build=build,
    )


def test_discovery_lists_all_downloaded_tags_without_loading_or_pulling(catalog):
    catalog.response.read.return_value = json.dumps({"models": [
        {"name": "zeta:8b"}, {"name": "alpha:14b"}, {"model": "hf.co/user/local:Q6_K"},
        {"name": "alpha:14b"}, {}, None, {"name": "bad name"}, {"name": "x" * 201},
    ]}).encode()
    assert ollama_models.discover_ollama_models(catalog.settings) == (
        "alpha:14b", "hf.co/user/local:Q6_K", "zeta:8b")
    catalog.opener.open.assert_called_once_with("http://127.0.0.1:11434/api/tags", timeout=2)
    catalog.response.read.assert_called_once_with(1_000_001)
    # Proxy bypass and redirect rejection keep the configured local service local.
    handlers = catalog.build.call_args.args
    assert handlers[0].proxies == {}
    assert handlers[1].redirect_request() is None


def test_refresh_bypasses_cache_and_returns_newly_downloaded_models(catalog):
    assert ollama_models.discover_ollama_models(catalog.settings) == ("qwen-local:latest",)
    catalog.response.read.return_value = b'{"models":[{"name":"new:latest"}]}'
    assert ollama_models.discover_ollama_models(catalog.settings) == ("qwen-local:latest",)
    assert catalog.opener.open.call_count == 1
    assert ollama_models.discover_ollama_models(catalog.settings, refresh=True, strict=True) == ("new:latest",)
    catalog.opener.open.assert_called_with("http://127.0.0.1:11434/api/tags", timeout=5)


def test_refresh_failure_keeps_previous_catalog(catalog):
    assert ollama_models.discover_ollama_models(catalog.settings) == ("qwen-local:latest",)
    catalog.opener.open.side_effect = TimeoutError()
    with pytest.raises(ProviderError, match="Your current selection was kept"):
        ollama_models.discover_ollama_models(catalog.settings, refresh=True, strict=True)
    assert ollama_models.discover_ollama_models(catalog.settings) == ("qwen-local:latest",)


def test_offline_initial_discovery_uses_configured_fallback_and_backs_off(catalog):
    catalog.opener.open.side_effect = OSError()
    assert ollama_models.discover_ollama_models(catalog.settings) == ("default:latest",)
    assert ollama_models.discover_ollama_models(catalog.settings) == ("default:latest",)
    assert catalog.opener.open.call_count == 1
    with pytest.raises(ProviderError):
        ollama_models.discover_ollama_models(catalog.settings, refresh=True, strict=True)
    assert catalog.opener.open.call_count == 2


def test_empty_catalog_is_authoritative_not_a_fake_default(catalog):
    catalog.response.read.return_value = b'{"models":[]}'
    assert ollama_models.discover_ollama_models(catalog.settings, refresh=True, strict=True) == ()
    assert ollama_models.discover_ollama_models(catalog.settings) == ()


def test_cache_does_not_leak_models_between_servers(catalog):
    ollama_models.discover_ollama_models(catalog.settings)
    catalog.settings.ollama_base_url = "http://localhost:11435"
    catalog.opener.open.side_effect = OSError()
    assert ollama_models.discover_ollama_models(catalog.settings) == ("default:latest",)


@pytest.mark.parametrize("raw", [b"bad json", b"[]", b"{}", b'{"models":null}', b"x" * 1_000_001],
                         ids=["json", "list", "missing", "null", "oversized"])
def test_invalid_response_is_a_refresh_error(catalog, raw):
    catalog.response.read.return_value = raw
    with pytest.raises(ProviderError):
        ollama_models.discover_ollama_models(catalog.settings, refresh=True, strict=True)


@pytest.mark.parametrize("url", ["https://localhost:11434", "http://example.com:11434",
                               "http://user:secret@127.0.0.1:11434"])
def test_discovery_rejects_unsafe_endpoints(catalog, url):
    catalog.settings.ollama_base_url = url
    with pytest.raises(ProviderError):
        ollama_models.discover_ollama_models(catalog.settings, refresh=True, strict=True)
    catalog.opener.open.assert_not_called()


@pytest.fixture
def ollama_api(tmp_path, monkeypatch):
    settings = replace(settings_for(tmp_path), ollama_base_url="http://127.0.0.1:1",
                       llm_provider="openai", openai_planner_model="openai-test-model")
    state = SimpleNamespace(models=[settings.ollama_model, "new-local:9b"], offline=False, calls=[])
    def discover(_settings, **kwargs):
        state.calls.append(kwargs)
        if state.offline and kwargs.get("strict"):
            raise ProviderError("Ollama is unavailable. Your current selection was kept.")
        return tuple(state.models)
    monkeypatch.setattr("darius_api.main.discover_ollama_models", discover)
    monkeypatch.setattr("darius_api.main.discover_openai_models", lambda *_args, **_kwargs: ("openai-test-model",))
    monkeypatch.setattr("darius_api.main.discover_opencode_models", lambda *_args, **_kwargs: ("test-free",))
    monkeypatch.setattr("darius_api.main.opencode_model_capabilities", lambda *_args: {})
    monkeypatch.setattr(OllamaPlannerProvider, "ready", lambda self: True)
    app = create_app(settings)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, app=app, state=state, settings=settings)


def test_settings_list_installed_models_and_refresh_without_switching(ollama_api):
    client, state = ollama_api.client, ollama_api.state
    before = client.get("/api/v1/settings/llm").json()
    assert next(item for item in before["providers"] if item["id"] == "ollama")["models"] == state.models
    state.models.append("downloaded-later:14b")
    response = client.post("/api/v1/settings/llm/ollama/models/refresh")
    assert response.status_code == 200
    assert response.json()["models"] == state.models
    assert state.calls[-1] == {"refresh": True, "strict": True}
    after = client.get("/api/v1/settings/llm").json()
    assert (after["provider"], after["model"], after["source"]) == (before["provider"], before["model"], before["source"])


def test_downloaded_nondefault_ollama_model_saves_and_survives_restart(ollama_api):
    response = ollama_api.client.post("/api/v1/settings/llm", json={"provider": "ollama", "model": "new-local:9b"})
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "ollama" and response.json()["model"] == "new-local:9b"
    assert isinstance(ollama_api.app.state.planner_provider, OllamaPlannerProvider)
    assert ollama_api.app.state.planner_provider._model() == "new-local:9b"
    with TestClient(create_app(ollama_api.settings)) as client:
        restored = client.get("/api/v1/settings/llm").json()
        assert restored["model"] == "new-local:9b" and restored["source"] == "saved"


def test_missing_or_unreachable_model_cannot_replace_saved_selection(ollama_api):
    client, state = ollama_api.client, ollama_api.state
    before = client.get("/api/v1/settings/llm").json()
    response = client.post("/api/v1/settings/llm", json={"provider": "ollama", "model": "not-installed:latest"})
    assert response.status_code == 422
    state.offline = True
    assert client.post("/api/v1/settings/llm/ollama/models/refresh").status_code == 502
    assert client.post("/api/v1/settings/llm", json={"provider": "ollama", "model": "new-local:9b"}).status_code == 502
    after = client.get("/api/v1/settings/llm").json()
    assert (after["provider"], after["model"]) == (before["provider"], before["model"])


@pytest.mark.parametrize("provider,models", [("openai", ["openai-test-model"]), ("opencode", ["test-free"])])
def test_existing_cloud_refresh_routes_are_unchanged(ollama_api, provider, models):
    response = ollama_api.client.post(f"/api/v1/settings/llm/{provider}/models/refresh")
    assert response.status_code == 200
    assert response.json()["id"] == provider
    assert response.json()["models"] == models
