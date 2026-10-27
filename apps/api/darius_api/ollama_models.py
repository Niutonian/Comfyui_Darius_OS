"""Read-only discovery of installed Ollama models; never pull or load a model."""
from __future__ import annotations

import json
import re
import time
import urllib.request
from urllib.parse import urlparse

from .config import Settings
from .providers import ProviderError

_cache: tuple[str, float, tuple[str, ...]] = ("", 0.0, ())
_failure: tuple[str, float] = ("", 0.0)


def discover_ollama_models(settings: Settings, *, refresh: bool = False, strict: bool = False) -> tuple[str, ...]:
    global _cache, _failure
    endpoint = settings.ollama_base_url.rstrip("/")
    cached_endpoint, cached_at, cached = _cache
    fallback = cached if cached_endpoint == endpoint else ((settings.ollama_model,) if settings.ollama_model else ())
    now = time.monotonic()
    if not refresh and cached_endpoint == endpoint and now - cached_at < 60:
        return cached
    if not refresh and _failure[0] == endpoint and now - _failure[1] < 15:
        return fallback

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    try:
        parsed = urlparse(endpoint)
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ProviderError("OLLAMA_BASE_URL must point to a loopback server.")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(endpoint + "/api/tags", timeout=5 if refresh else 2) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Oversized model catalog")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise ValueError("Invalid model catalog")
        models = set()
        for item in payload["models"]:
            if not isinstance(item, dict):
                continue
            identifier = item.get("name") or item.get("model")
            if (isinstance(identifier, str) and len(identifier) <= 200
                    and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", identifier)):
                models.add(identifier)
        result = tuple(sorted(models, key=lambda name: (name.casefold(), name)))
        _cache, _failure = (endpoint, time.monotonic(), result), ("", 0.0)
        return result
    except (OSError, ValueError, ProviderError):
        _failure = (endpoint, time.monotonic())
        if strict:
            raise ProviderError("Could not refresh Ollama models. Make sure Ollama is running on the Darius server, then retry. Your current selection was kept.") from None
        return fallback
