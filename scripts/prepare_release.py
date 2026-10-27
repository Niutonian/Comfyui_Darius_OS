"""Create a reviewed source-only repository without copying development history."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_audit as audit

ROOT = Path(__file__).resolve().parents[1]
POLICY = "workflow-metadata-privacy-v1"


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def sanitize(name: str, content: bytes) -> tuple[bytes, list[str]]:
    """Only known non-executable authoring fields may change."""
    is_export = name.startswith("workflows/canvas/minimax-h3-") and name.endswith("/export.json")
    is_ui = ((name.startswith("workflows/canvas/minimax-h3-") and name.endswith("/source.ui.json"))
             or name == "workflows/defaults/Darius_MiniMax _ref2video_Singularity.json")
    if not (is_export or is_ui):
        return content, []
    value = json.loads(content)
    before = deepcopy(value)
    changes = []
    if is_export:
        workflow = value.get("data", {}).get("workflow")
        if isinstance(workflow, str) and (":" in workflow or workflow.startswith("/")):
            value["data"]["workflow"] = workflow.replace("\\", "/").rsplit("/", 1)[-1]
            changes.append("data.workflow: retain portable basename only")
        assert value["data"]["prompt"] == before["data"]["prompt"], "Executable export graph changed"
    else:
        for index, node in enumerate(value.get("nodes", [])):
            for field in ("widgets_values", "widgets_values_named"):
                widgets = node.get(field)
                if isinstance(widgets, dict) and widgets.get("videopreview"):
                    widgets["videopreview"] = {}
                    changes.append(f"nodes[{index}].{field}.videopreview: clear cached preview")
        # Cache removal cannot change node wiring, executable widget values,
        # source API files, prompts or the compiled versioned templates.
        masked_before = deepcopy(before)
        for node in masked_before.get("nodes", []):
            for field in ("widgets_values", "widgets_values_named"):
                if isinstance(node.get(field), dict) and node[field].get("videopreview"):
                    node[field]["videopreview"] = {}
        assert value == masked_before, "Unexpected source UI mutation"
    return (json_bytes(value), changes) if changes else (content, [])


def export(destination: Path, *, source: Path = ROOT) -> dict:
    source = source.resolve()
    destination = destination.resolve()
    allowed = (source / ".tmp/releases").resolve()
    if not destination.is_relative_to(allowed) or destination == allowed:
        raise ValueError("Destination must be a new directory inside .tmp/releases/")
    if destination.exists():
        raise ValueError("Destination already exists; choose a new release directory")
    # A caller's GIT_DIR/index overrides or global init templates must not
    # redirect staging into the development repository or install hooks.
    git_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    git_env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", *args], cwd=source, env=git_env)
    if git("ls-files", "-ci", "--exclude-standard").strip():
        raise ValueError("Tracked ignored files remain; review the source index first")
    names = sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")) - {""})
    blobs: dict[str, bytes] = {}
    records = []
    for name in names:
        if name == "release-provenance.json":
            continue  # Always create a new receipt, never hash an older receipt as source.
        path = source / name
        if not path.exists():
            continue  # Existing intentional deletions do not enter the snapshot.
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError(f"Source link escapes the repository: {name}")
        if not path.is_file():
            continue  # Submodules are transferred as gitlinks below.
        if audit.private_path(name) or path.stat().st_size > 100 * 1024 * 1024:
            raise ValueError(f"Private or oversized publication candidate: {name}")
        original = path.read_bytes()
        content, changes = sanitize(name, original)
        if audit.text_path(name):
            findings = audit.scan(name, content) + audit.privacy_scan(name, content)
            if findings:
                raise ValueError("\n".join(findings))
        blobs[name] = content
        if changes:
            records.append({"path": name, "changes": changes,
                            "privateOriginalSha256": hashlib.sha256(original).hexdigest(),
                            "releaseSha256": hashlib.sha256(content).hexdigest()})
    # Keep API/template graph checksums intact. Only the source UI checksum
    # changes; exports hash the prompt graph, not its machine path envelope.
    for record in list(records):
        name = record["path"]
        if name.startswith("workflows/canvas/") and name.endswith("/source.ui.json"):
            manifest_name = str(Path(name).with_name("manifest.json")).replace("\\", "/")
            manifest = json.loads(blobs[manifest_name])
            if manifest["sourceUiDigest"] != record["privateOriginalSha256"]:
                raise ValueError(f"Original source manifest mismatch: {manifest_name}")
            manifest["sourceUiDigest"] = record["releaseSha256"]
            manifest["sourceUiPrivacyVersion"] = POLICY
            manifest["privateOriginalSourceUiDigest"] = record["privateOriginalSha256"]
            blobs[manifest_name] = json_bytes(manifest)
    for name in blobs:
        if name.endswith(("/template.api.json", "/source.api.json")):
            if blobs[name] != (source / name).read_bytes():
                raise ValueError(f"Executable workflow artifact changed: {name}")
    receipt = {"schemaVersion": 1, "policy": POLICY, "history": "fresh repository; development history excluded",
               "sourceFiles": len(blobs), "sanitizedArtifacts": records,
               "files": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(blobs.items())}}
    destination.mkdir(parents=True)
    for name, content in blobs.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (destination / "release-provenance.json").write_bytes(json_bytes(receipt))
    def release_git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=destination, env=git_env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    release_git("init", "--initial-branch=main", "--template=")
    # Stage only copied source, never data generated by subsequent validation.
    release_git("-c", "core.autocrlf=false", "add", "--all")
    for entry in git("ls-files", "--stage", "-z").decode().split("\0"):
        if entry.startswith("160000 "):
            metadata, name = entry.split("\t", 1)
            oid = metadata.split()[1]
            (destination / name).mkdir(parents=True, exist_ok=True)
            release_git("update-index", "--add", "--cacheinfo", f"160000,{oid},{name}")
    # No commit identity, history, remote, hooks, local config or credentials
    # are copied. Commit/push are separate deliberate owner actions.
    subprocess.run([sys.executable, "scripts/release_audit.py", "--history", "--privacy"], cwd=destination, env=git_env, check=True)
    return receipt


def archive_release(destination: Path, archive: Path) -> None:
    """Archive reviewed sources under one Darius/ folder, never runtime files."""
    receipt = json.loads((destination / 'release-provenance.json').read_text(encoding='utf-8'))
    for name, expected in receipt['files'].items():
        path = destination / name
        if not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Release receipt contains a path outside the source folder')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Release source changed after export: {name}')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as bundle:
        for name in [*sorted(receipt['files']), 'release-provenance.json']:
            bundle.write(destination / name, f'Darius/{name}')
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + '.sha256').write_text(
        f'{checksum}  {archive.name}\n', encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New directory under .tmp/releases/")
    parser.add_argument('--zip', type=Path, help='Also create a new ZIP with a single Darius/ folder')
    args = parser.parse_args()
    try:
        receipt = export(args.destination)
        if args.zip:
            archive_release(args.destination, args.zip)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Release preparation stopped: {exc}", file=sys.stderr)
        return 1
    print(f"Prepared {receipt['sourceFiles']} source files; sanitized {len(receipt['sanitizedArtifacts'])} authoring artifacts.")
    print("Originals preserved. No development history, commit, remote or push was copied or created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
