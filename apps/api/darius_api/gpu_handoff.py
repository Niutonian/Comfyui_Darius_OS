"""Serialize local LLM and ComfyUI GPU ownership across API/worker processes."""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

_leases = threading.local()


@contextmanager
def gpu_lease(settings, timeout: float | None = None):
    """Use an OS file lock so Ollama and ComfyUI never own the GPU together."""
    lock_path = Path(settings.data_dir) / "gpu-owner.lock"
    key = str(lock_path.resolve())
    held = getattr(_leases, "held", set())
    if key in held:
        yield  # Worker owns capacity before claim; provider shares that lease.
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + (timeout if timeout is not None else settings.ollama_gpu_wait_seconds)
    acquired = False
    try:
        while not acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for the local GPU")
                time.sleep(0.25)
        _leases.held = held | {key}
        yield
    finally:
        if acquired:
            _leases.held = held
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def unload_idle_comfy(settings) -> None:
    """Release idle ComfyUI caches, never cancel work or contact a remote host.

    Caller holds gpu_lease. This additional queue check protects jobs submitted
    directly to ComfyUI, which do not participate in Darius' file lock.
    """
    parsed = urlparse(settings.comfyui_base_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password):
        raise RuntimeError("Idle ComfyUI GPU handoff requires a loopback COMFYUI_BASE_URL")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(settings.comfyui_base_url + "/queue", timeout=5) as response:
            queue = json.load(response)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            return  # Chat still works when ComfyUI is not running.
        raise RuntimeError("Could not check ComfyUI's queue before waking the local model") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError("Could not check ComfyUI's queue before waking the local model") from exc
    if (not isinstance(queue, dict) or not isinstance(queue.get("queue_running"), list)
            or not isinstance(queue.get("queue_pending"), list)):
        raise RuntimeError("ComfyUI returned an invalid queue; its caches were not changed")
    if queue["queue_running"] or queue["queue_pending"]:
        raise RuntimeError("ComfyUI is busy. Retry after its current jobs finish; no work was cancelled.")
    request = urllib.request.Request(
        settings.comfyui_base_url + "/free",
        data=b'{"unload_models":true,"free_memory":true}',
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with opener.open(request, timeout=10):
            pass
    except OSError as exc:
        raise RuntimeError("Could not release ComfyUI's idle GPU cache") from exc


def unload_ollama(settings, timeout: float = 30) -> None:
    """Release resident GPU models without loading a missing configured model."""
    parsed = urlparse(settings.ollama_base_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password):
        raise RuntimeError("OLLAMA_BASE_URL must point to a loopback server")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    stage = "checking running models"

    def residents():
        with opener.open(settings.ollama_base_url + "/api/ps", timeout=3) as response:
            data = json.load(response)
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise ValueError("invalid running-model list")
        result = set()
        for item in data["models"]:
            if not isinstance(item, dict):
                raise ValueError("invalid running model")
            name = item.get("name") or item.get("model")
            size = item.get("size_vram")
            if not isinstance(name, str) or not name.strip() or (size is not None and (type(size) is not int or size < 0)):
                raise ValueError("invalid running model")
            if size != 0:  # Keep confirmed CPU-only models; unknown residency is conservative.
                result.add(name)
        return result

    try:
        try:
            models = residents()
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ConnectionRefusedError):
                return  # No running daemon at the configured local endpoint.
            raise
        if not models:
            return
        stage = "unloading running models"
        for model in sorted(models):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("unload deadline reached")
            request = urllib.request.Request(
                settings.ollama_base_url + "/api/generate",
                data=json.dumps({"model": model, "stream": False, "keep_alive": 0}).encode(),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            try:
                with opener.open(request, timeout=remaining):
                    pass
            except urllib.error.HTTPError as exc:
                # Another client may have unloaded/deleted it since the snapshot.
                # A 404 alone never proves the GPU was released.
                if exc.code != 404 or model in residents():
                    raise
        stage = "verifying GPU release"
        while time.monotonic() < deadline:
            if not residents():
                return
            time.sleep(0.25)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Ollama GPU handoff failed while {stage} (HTTP {exc.code}). Check Ollama's local API address and running models, then retry; no render was submitted.") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Ollama GPU handoff failed while {stage} ({type(exc).__name__}). Check that Ollama is responding, then retry; no render was submitted.") from exc
    raise RuntimeError("Ollama still reports GPU-resident models. Close other Ollama clients and retry; no render was submitted.")
