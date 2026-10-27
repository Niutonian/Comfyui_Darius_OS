"""Read-only publication checks. Findings never include credential values."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", ".md", ".toml", ".yaml", ".yml", ".ps1", ".bat", ".sh", ".ini", ".example", ".txt", ".cfg", ".conf", ".lock", ".pem", ".key"}
PATTERNS = [
    re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    re.compile(rb"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,})"),
    re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(rb"\bhf_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def text_path(name: str) -> bool:
    path = Path(name)
    return (path.suffix.lower() in TEXT or path.name.startswith(".env")
            or path.name in {".gitignore", ".gitmodules", "Dockerfile", "Caddyfile"})


def private_path(name: str) -> bool:
    path = Path(name)
    folders = {"data", "assets", "demo", ".tmp", "screenshots", "ui-review",
               "recordings", "backups", "test-results", "playwright-report"}
    return ((bool(path.parts) and path.parts[0] == "recast")
            or bool(set(path.parts) & folders)
            or path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".har", ".dmp", ".heapsnapshot", ".gguf", ".safetensors", ".ckpt", ".onnx", ".pth", ".pem", ".key", ".pfx", ".p12"}
            or (path.name.startswith(".env") and not path.name.endswith(".example"))
            or path.name in {"darius-lan-ca.cer", "darius-lan-info.json"}
            or path.name == "CURRENT_STATUS.md"
            or (len(path.parts) == 1 and "HANDOFF" in path.name))


def scan(label: str, content: bytes) -> list[str]:
    findings = []
    for number, line in enumerate(content.splitlines(), 1):
        if any(pattern.search(line) for pattern in PATTERNS):
            findings.append(f"Possible credential: {label}:{number} (review locally)")
    return findings


def privacy_scan(label: str, content: bytes) -> list[str]:
    decoded = content.decode("utf-8", errors="replace").replace("\\\\", "/").replace("\\", "/").casefold()
    locations = [ROOT.as_posix().casefold(), Path.home().as_posix().casefold()]
    if (any(value in decoded for value in locations)
            or re.search(r"[a-z]:/(?:users|claude)/[^\s\"<>]+", decoded)):
        return [f"Personal workstation path: {label} (review locally)"]
    return []


def main() -> int:
    # Windows consoles may not encode Unicode filenames. Keep every finding
    # reportable rather than crashing halfway through a privacy audit.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="Also inspect text blobs reachable from local Git refs")
    parser.add_argument("--privacy", action="store_true", help="Also block personal artifacts, workstation paths and historical screenshots")
    args = parser.parse_args()
    findings: list[str] = []
    ignored = git("ls-files", "-ci", "--exclude-standard").decode().splitlines()
    findings.extend(f"Tracked but ignored: {name}" for name in ignored)
    names = sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")) - {""})
    count = 0
    for name in names:
        path = ROOT / name
        if not path.is_file():
            continue
        count += 1
        if path.stat().st_size > 100 * 1024 * 1024:
            findings.append(f"File exceeds 100 MiB: {name}")
            continue
        if text_path(name):
            content = path.read_bytes()
            findings.extend(scan(name, content))
            if args.privacy:
                findings.extend(privacy_scan(name, content))
        if args.privacy and private_path(name):
            findings.append(f"Local/private artifact in publication candidates: {name}")
    history_count = 0
    if args.history:
        if args.privacy:
            historical_names = {n.lstrip("\n") for n in git("log", "--all", "--format=", "--name-only", "-z").decode().split("\0") if n.strip()}
            private_names = [n for n in historical_names if private_path(n)]
            if private_names:
                findings.append(f"Git history retains {len(private_names)} local/private artifact paths; ignoring or deleting their current copies does not remove that history.")
        objects = []
        for entry in git("rev-list", "--objects", "--all").decode().splitlines():
            oid, _, name = entry.partition(" ")
            if text_path(name):
                objects.append((oid, name))
        # Batch mode avoids one process per historical file. Blob contents stay local.
        result = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT,
                                input="".join(oid + "\n" for oid, _ in objects).encode(),
                                stdout=subprocess.PIPE, check=True).stdout
        offset = 0
        for oid, name in objects:
            end = result.index(b"\n", offset)
            header = result[offset:end].split()
            size = int(header[2])
            content = result[end + 1:end + 1 + size]
            offset = end + size + 2
            if header[1] == b"blob":
                history_count += 1
                findings.extend(scan(f"history {oid[:12]} {name}", content))
                if args.privacy:
                    findings.extend(privacy_scan(f"history {oid[:12]} {name}", content))
    print(f"Checked {count} candidate files and {history_count} historical text blobs.")
    for finding in findings:
        print(finding)
    print("FAIL: publication review required" if findings else "PASS: requested publication checks passed.")
    print("This heuristic check does not replace reviewing the publication diff and third-party licenses.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
