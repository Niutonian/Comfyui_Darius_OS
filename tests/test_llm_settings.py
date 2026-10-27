from __future__ import annotations

import json
from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from darius_api.main import create_app
from darius_api.providers import DeepSeekPlannerProvider, OpenCodePlannerProvider
from test_media_backend import settings_for


@pytest.fixture(autouse=True)
def offline_model_catalogs(monkeypatch):
    # Settings tests must not contact real cloud accounts or the user's Ollama.
    monkeypatch.setattr("darius_api.main.discover_openai_models", lambda settings, **kwargs: (settings.openai_planner_model,))
    monkeypatch.setattr("darius_api.main.discover_ollama_models", lambda settings, **kwargs: (settings.ollama_model,))
    monkeypatch.setattr("darius_api.main.discover_opencode_models", lambda *args, **kwargs: ("test-free",))
    monkeypatch.setattr("darius_api.main.opencode_model_capabilities", lambda *args: {})


def configured_settings(tmp_path):
    return replace(
        settings_for(tmp_path),
        llm_provider="openai",
        openai_api_key="openai-private-test-key",
        openai_planner_model="openai-test-model",
        deepseek_api_key="deepseek-private-test-key",
        deepseek_model="deepseek-flash",
    )


def test_llm_settings_expose_choices_without_credentials(tmp_path, monkeypatch):
    settings = configured_settings(tmp_path)
    monkeypatch.setattr("darius_api.main.discover_opencode_models", lambda *_args, **_kwargs: (
        "nemotron-3.5-lightning-free", "nemotron-3-ultra-free",
        "mimo-v2.6-flash-free", "longcat-2.5-preview-free",
        "ling-3.0-flash-fin-free", "muse-spark-1.3-contributor-free",
        "space-bunny-free",
    ))
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/settings/llm")
        assert response.status_code == 200
        payload = response.json()

    assert payload == {
        "provider": "openai",
        "model": "openai-test-model",
        "ready": True,
        "credential_configured": True,
        "source": "environment",
        "reasoning_effort": "auto",
        "providers": [
            {
                "id": "openai",
                "label": "OpenAI",
                "models": ["openai-test-model"],
                "credential_configured": True,
                "model_capabilities": {},
                "reasoning_efforts": {"openai-test-model": ["auto"]},
            },
            {
                "id": "deepseek",
                "label": "DeepSeek",
                "models": ["deepseek-flash", "deepseek-v4-pro"],
                "credential_configured": True,
                "model_capabilities": {},
                "reasoning_efforts": {},
            },
            {
                "id": "ollama",
                "label": "Ollama (local)",
                "models": [settings.ollama_model],
                "credential_configured": True,
                "model_capabilities": {},
                "reasoning_efforts": {},
            },
            {
                "id": "llamacpp",
                "label": "llama.cpp (local)",
                "models": [settings.llamacpp_model],
                "credential_configured": True,
                "model_capabilities": {},
                "reasoning_efforts": {},
            },
            {
                "id": "opencode",
                "label": "OpenCode Free",
                "models": [
                    "nemotron-3.5-lightning-free", "nemotron-3-ultra-free",
                    "mimo-v2.6-flash-free", "longcat-2.5-preview-free",
                    "ling-3.0-flash-fin-free", "muse-spark-1.3-contributor-free",
                    "space-bunny-free",
                ],
                "credential_configured": True,
                "model_capabilities": {},
                "reasoning_efforts": {},
            },
        ],
    }
    encoded = json.dumps(payload)
    assert settings.openai_api_key not in encoded
    assert settings.deepseek_api_key not in encoded


def test_llm_selection_switches_runtime_and_survives_restart(tmp_path):
    settings = configured_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        saved = client.post(
            "/api/v1/settings/llm",
            json={"provider": "deepseek", "model": "deepseek-v4-pro"},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["source"] == "saved"
        assert saved.json()["ready"] is True
        assert isinstance(app.state.planner_provider, DeepSeekPlannerProvider)
        assert app.state.planner_provider.model_name == "deepseek-v4-pro"

    restarted = create_app(settings)
    with TestClient(restarted) as client:
        restored = client.get("/api/v1/settings/llm")
        assert restored.status_code == 200
        assert restored.json()["provider"] == "deepseek"
        assert restored.json()["model"] == "deepseek-v4-pro"
        assert restored.json()["source"] == "saved"
        assert isinstance(restarted.state.planner_provider, DeepSeekPlannerProvider)


def test_llm_settings_reject_invalid_or_secret_fields(tmp_path):
    with TestClient(create_app(configured_settings(tmp_path))) as client:
        unsupported = client.post(
            "/api/v1/settings/llm",
            json={"provider": "deepseek", "model": "invented-model"},
        )
        assert unsupported.status_code == 422
        assert unsupported.json()["detail"] == "unsupported DeepSeek model"

        invalid = client.post(
            "/api/v1/settings/llm",
            json={"provider": "openai", "model": "bad model with spaces"},
        )
        assert invalid.status_code == 422

        secret = client.post(
            "/api/v1/settings/llm",
            json={"provider": "openai", "model": "openai-test-model", "api_key": "must-not-store"},
        )
        assert secret.status_code == 422


def test_llm_selection_can_switch_to_opencode_free_without_a_key(tmp_path, monkeypatch):
    settings = configured_settings(tmp_path)
    monkeypatch.setattr("darius_api.main.discover_opencode_models", lambda *_args, **_kwargs: ("test-free",))
    monkeypatch.setattr("darius_api.providers.discover_opencode_models", lambda *_args, **_kwargs: ("test-free",))
    app = create_app(settings)
    with TestClient(app) as client:
        saved = client.post("/api/v1/settings/llm", json={"provider": "opencode", "model": "test-free"})
        assert saved.status_code == 200, saved.text
        assert saved.json()["credential_configured"] is True
        assert isinstance(app.state.planner_provider, OpenCodePlannerProvider)
        assert app.state.planner_provider.model_name == "test-free"
