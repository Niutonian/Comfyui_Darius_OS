"""Authenticated, bounded local diagnostics; no caller-supplied paths or URLs."""
from datetime import datetime, timezone
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import secrets
import threading
import urllib.request
from urllib.parse import urlparse

_lock = threading.Lock()
_loggers = {}


def access_key(settings):
    path = settings.data_dir / "diagnostics" / "access-code.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    with path.open('rb') as stream:
        raw = stream.read(2049)
    if len(raw) > 2048:
        raise ValueError('Diagnostics access code file is too large; reset it locally in the Darius manager.')
    key = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', key):
        raise ValueError("Diagnostics access code is invalid; restore or remove the access-code file locally.")
    return key


def reset_access_key(settings):
    path = settings.data_dir / 'diagnostics' / 'access-code.txt'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.access-code-' + secrets.token_hex(12) + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            stream.write(secrets.token_urlsafe(32))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def redact(value):
    value = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", str(value))
    value = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)((?:api[_-]?key|authorization|password|secret|access[_-]?token)[\"']?\s*[=:]\s*[\"']?)[^\s\"',;}]+", r"\1[REDACTED]", value)
    return re.sub(r"\b(?:sk-|hf_)[A-Za-z0-9_-]{12,}\b", "[REDACTED]", value)


def record(settings, source, level, event, **details):
    try:
        path = (settings.data_dir / "diagnostics" / "backend.jsonl").resolve()
        with _lock:
            logger = _loggers.get(path)
            if logger is None:
                path.parent.mkdir(parents=True, exist_ok=True)
                logger = logging.Logger(str(path), logging.INFO)
                handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8", delay=True)
                handler.setFormatter(logging.Formatter("%(message)s"))
                logger.addHandler(handler)
                _loggers[path] = logger
            logger.info(redact(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "source": source,
                "level": level, "event": event, **details}, ensure_ascii=False, default=str)))
    except (OSError, ValueError):
        pass


def tail(path, byte_limit=48000):
    try:
        with Path(path).open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - byte_limit))
            data = stream.read(byte_limit).decode("utf-8", errors="replace")
        if size > byte_limit:
            data = data.partition("\n")[2]
        return redact("\n".join(data.splitlines()[-200:]))
    except OSError:
        return ""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def local_json(base_url, endpoint):
    target = urlparse(base_url)
    if target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost", "::1"} or target.username or target.password:
        raise ValueError("Only loopback services can be inspected")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(base_url + endpoint, timeout=2) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Service log response exceeded its safety limit")
        return json.loads(raw)


def service_snapshot(settings, provider, include_logs=True):
    checks = [{"name": "Backend", "state": "ready", "detail": "API responding"}]
    comfy_text = ""
    try:
        queue = local_json(settings.comfyui_base_url, "/queue")
        checks.append({"name": "ComfyUI", "state": "ready", "detail": f"{len(queue.get('queue_running', []))} running · {len(queue.get('queue_pending', []))} pending"})
        if include_logs:
            try:
                logs = local_json(settings.comfyui_base_url, "/internal/logs")
                comfy_text = redact("\n".join(str(logs).splitlines()[-200:]))[-48000:]
            except (OSError, ValueError):
                comfy_text = "Terminal logs unavailable on this ComfyUI installation. Backend activity and project failures remain available."
    except (OSError, ValueError) as exc:
        checks.append({"name": "ComfyUI", "state": "offline", "detail": type(exc).__name__})
    if provider in {"llamacpp", "ollama"}:
        try:
            if provider == "llamacpp":
                props = local_json(settings.llamacpp_base_url, "/props")
                detail = f"Context: {props.get('default_generation_settings', {}).get('n_ctx', 'unknown')} · {'sleeping' if props.get('is_sleeping') else 'available'}"
            else:
                local_json(settings.ollama_base_url, "/api/tags")
                detail = "Local service responding"
            checks.append({"name": provider, "state": "ready", "detail": detail})
        except (OSError, ValueError) as exc:
            checks.append({"name": provider, "state": "offline", "detail": type(exc).__name__})
    return checks, comfy_text
