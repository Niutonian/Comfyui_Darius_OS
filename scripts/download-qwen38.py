"""Pinned, resumable public GGUF download; never downloads executable model code."""
import hashlib
import json
import os
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

FILENAME = "Qwen3.8-27B-ByteShape-IQ4_XS-3.84bpw-ASCII-P1M.gguf"
SIZE = 12252882720
SHA256 = "d533c568ba028fb7bc24d646d9f0259341a388fb2535e559fd0bc62275a55a4d"
URL = "https://huggingface.co/islamsidratul/Qwen3.8-27B-ByteShape-IQ4_XS-ASCII-GGUF/resolve/main/" + FILENAME + "?download=true"
DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "models" / "llamacpp"
CHUNK = 32 * 1024 * 1024


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    if os.environ.get("LOCALAPPDATA"):
        cached = Path(os.environ["LOCALAPPDATA"]) / "Darius" / "models" / "llamacpp" / FILENAME
        if cached.exists():
            if cached.stat().st_size != SIZE or digest(cached) != SHA256:
                raise RuntimeError("Existing SSD-cached model does not match its published checksum.")
            print("Verified existing SSD-cached model:", cached, flush=True)
            return
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    final = DIRECTORY / FILENAME
    partial = DIRECTORY / (FILENAME + ".partial")
    manifest = DIRECTORY / (FILENAME + ".download.json")
    if final.exists():
        if final.stat().st_size != SIZE or digest(final) != SHA256:
            raise RuntimeError("Existing GGUF does not match its published checksum; it was not overwritten.")
        print("Verified existing model:", final, flush=True)
        return
    if manifest.exists():
        state = json.loads(manifest.read_text())
        if state.get("sha256") != SHA256 or not partial.exists():
            raise RuntimeError("Download resume manifest does not match the pinned model.")
    else:
        prefix = partial.stat().st_size if partial.exists() else 0
        if prefix > SIZE:
            raise RuntimeError("Partial download exceeds the pinned file size.")
        state = {"sha256": SHA256, "prefix": prefix, "completed": []}
    lock = threading.Lock()
    def save_state():
        temporary = manifest.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        temporary.replace(manifest)
    save_state()
    if not partial.exists():
        partial.touch()
    ranges = [(start, min(start + CHUNK, SIZE) - 1) for start in range(state["prefix"], SIZE, CHUNK)]
    completed = set(state["completed"])
    finished = state["prefix"] + sum(end - start + 1 for start, end in ranges if start in completed)
    print(f"Resuming verified-length transfer at {finished / SIZE:.1%}; 6 parallel connections", flush=True)

    def fetch(bounds):
        start, end = bounds
        expected = f"bytes {start}-{end}/{SIZE}"
        for attempt in range(4):
            try:
                request = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"})
                with urllib.request.urlopen(request, timeout=90) as response:
                    if response.status != 206 or response.headers.get("Content-Range") != expected:
                        raise RuntimeError("Server did not honor the exact requested byte range")
                    data = response.read(end - start + 2)
                if len(data) != end - start + 1:
                    raise RuntimeError("Incomplete model byte range")
                with lock:
                    with partial.open("r+b") as stream:
                        stream.seek(start)
                        stream.write(data)
                        stream.flush()
                    state["completed"].append(start)
                    save_state()
                return len(data)
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch, bounds) for bounds in ranges if bounds[0] not in completed]
        for future in as_completed(futures):
            finished += future.result()
            print(f"Downloaded {finished / 1e9:.2f} / {SIZE / 1e9:.2f} GB ({finished / SIZE:.1%})", flush=True)
    print("Verifying published SHA-256...", flush=True)
    if partial.stat().st_size != SIZE or digest(partial) != SHA256:
        raise RuntimeError("GGUF checksum mismatch; partial data kept for diagnosis, no model activated")
    partial.rename(final)
    manifest.unlink()
    print("Verified model:", final, flush=True)


if __name__ == "__main__":
    main()
