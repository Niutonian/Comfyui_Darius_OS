"""Publication must exclude private history and preserve executable workflows."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_USER_ROOT = "C:" + "/Users/" + "private-user"
spec = importlib.util.spec_from_file_location("prepare_release", ROOT / "scripts/prepare_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_release_zip_has_single_darius_folder_and_excludes_unlisted_data(tmp_path):
    directory = tmp_path / 'reviewed'
    directory.mkdir()
    content = b'@echo off\n'
    (directory / 'install.bat').write_bytes(content)
    (directory / 'private.txt').write_text('not part of the release')
    receipt = {'files': {'install.bat': hashlib.sha256(content).hexdigest()}}
    (directory / 'release-provenance.json').write_text(json.dumps(receipt))
    archive = tmp_path / 'Darius.zip'
    release.archive_release(directory, archive)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.namelist() == ['Darius/install.bat', 'Darius/release-provenance.json']
        assert bundle.read('Darius/install.bat') == content
    assert archive.with_suffix('.zip.sha256').read_text().startswith(hashlib.sha256(archive.read_bytes()).hexdigest())


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "development"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    write(root, ".gitignore", b"data/\n.tmp/\nassets/\n.env\n")
    write(root, "scripts/release_audit.py", (ROOT / "scripts/release_audit.py").read_bytes())
    write(root, "README.md", b"A source-only release.\n")
    write(root, "assets/private.png", b"private screenshot")
    git(root, "add", "--all")
    git(root, "add", "--force", "assets/private.png")
    git(root, "-c", "user.name=Release Test", "-c", "user.email=test@example.invalid", "commit", "-m", "Private development history")
    git(root, "rm", "--cached", "assets/private.png")
    write(root, "data/screenshots/test.png", b"personal test output")
    write(root, ".env", b"PRIVATE_SETTING=local-only\n")
    return root


def test_release_excludes_private_history_and_retains_only_sanitized_authoring_metadata(source):
    directory = "workflows/canvas/minimax-h3-reference-video-v1/"
    ui = {"nodes": [{"id": 1, "inputs": [{"link": 2}], "widgets_values": {
        "prompt": "Example prompt", "videopreview": {"params": {"fullpath": PRIVATE_USER_ROOT + "/output/clip.mp4"}}}}]}
    original = release.json_bytes(ui)
    write(source, directory + "source.ui.json", original)
    api = b'{"1":{"class_type":"Example","inputs":{"value":"unchanged"}}}\n'
    write(source, directory + "source.api.json", api)
    write(source, directory + "template.api.json", api)
    envelope = {"data": {"workflow": PRIVATE_USER_ROOT + "/workflow.json", "prompt": json.loads(api)}}
    write(source, directory + "export.json", release.json_bytes(envelope))
    manifest = {"sourceUiDigest": hashlib.sha256(original).hexdigest(), "templateDigest": "unchanged", "exportDigest": release.digest(envelope["data"]["prompt"])}
    write(source, directory + "manifest.json", release.json_bytes(manifest))
    destination = source / ".tmp/releases/preview"
    receipt = release.export(destination, source=source)
    assert len(receipt["sanitizedArtifacts"]) == 2
    assert not (destination / "data").exists()
    assert not (destination / ".env").exists()
    assert not (destination / "assets").exists()
    assert (source / "assets/private.png").read_bytes() == b"private screenshot"
    assert (source / (directory + "source.ui.json")).read_bytes() == original
    assert not git(destination, "log", "--all", "--format=%H").strip()
    assert not git(destination, "remote").strip()
    for name in ["source.api.json", "template.api.json"]:
        assert (destination / (directory + name)).read_bytes() == api
    public = json.loads((destination / (directory + "source.ui.json")).read_bytes())
    assert public["nodes"][0]["widgets_values"] == {"prompt": "Example prompt", "videopreview": {}}
    assert public["nodes"][0]["inputs"] == ui["nodes"][0]["inputs"]
    public_manifest = json.loads((destination / (directory + "manifest.json")).read_bytes())
    assert public_manifest["sourceUiDigest"] == hashlib.sha256((destination / (directory + "source.ui.json")).read_bytes()).hexdigest()
    assert public_manifest["templateDigest"] == manifest["templateDigest"]
    assert public_manifest["exportDigest"] == manifest["exportDigest"]
    assert "assets/private.png" not in git(destination, "ls-files").decode()


def test_unknown_personal_path_fails_before_creating_release(source):
    write(source, "unexpected.json", release.json_bytes({"path": PRIVATE_USER_ROOT + "/notes.txt"}))
    destination = source / ".tmp/releases/blocked"
    with pytest.raises(ValueError, match="Personal workstation path"):
        release.export(destination, source=source)
    assert not destination.exists()


def test_future_recast_experiments_cannot_enter_release_even_if_unignored(source):
    write(source, "recast/experiment.zip", b"private experimental bundle")
    with pytest.raises(ValueError, match="Private or oversized publication candidate"):
        release.export(source / ".tmp/releases/no-experiments", source=source)
    assert (source / "recast/experiment.zip").read_bytes() == b"private experimental bundle"


def test_clean_checkout_migrations_create_missing_database_parent(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    database = tmp_path / "fresh-install" / "data" / "darius.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "sqlite:///" + database.as_posix())
    assert not database.parent.exists()
    command.upgrade(config, "head")
    engine = create_engine("sqlite:///" + database.as_posix())
    assert "projects" in inspect(engine).get_table_names()
    engine.dispose()


def test_audit_reports_unicode_filenames_on_restricted_windows_consoles(source):
    write(source, "review/notes-\U0001f642.txt", (PRIVATE_USER_ROOT + "/private.txt").encode())
    result = subprocess.run([__import__("sys").executable, "scripts/release_audit.py", "--privacy"],
                            cwd=source, capture_output=True, env={**os.environ, "PYTHONIOENCODING":"ascii"})
    assert result.returncode == 1
    assert b"Personal workstation path" in result.stdout
    assert b"notes-\\U0001f642.txt" in result.stdout
    assert b"UnicodeEncodeError" not in result.stderr


def test_release_never_overwrites_existing_directory_or_exports_outside_scratch(source):
    with pytest.raises(ValueError, match="inside .tmp/releases"):
        release.export(source.parent / "outside", source=source)
    destination = source / ".tmp/releases/kept"
    destination.mkdir(parents=True)
    marker = write(destination, "keep.txt", b"preserved")
    with pytest.raises(ValueError, match="already exists"):
        release.export(destination, source=source)
    assert marker.read_bytes() == b"preserved"


def test_privacy_gate_detects_private_artifacts_even_after_current_removal(source):
    result = subprocess.run(["git", "log", "--all", "--format=", "--name-only"], cwd=source, capture_output=True, check=True)
    assert b"assets/private.png" in result.stdout
    result = subprocess.run(["git", "ls-files", "assets"], cwd=source, capture_output=True, check=True)
    assert not result.stdout.strip()
    result = subprocess.run([__import__("sys").executable, "scripts/release_audit.py", "--history", "--privacy"], cwd=source, capture_output=True, check=False)
    assert result.returncode == 1
    assert b"Git history retains" in result.stdout
    assert b"private screenshot" not in result.stdout


def test_inherited_git_overrides_cannot_redirect_release_staging(source, monkeypatch):
    before = git(source, "ls-files", "--stage")
    monkeypatch.setenv("GIT_DIR", str(source / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(source))
    release.export(source / ".tmp/releases/isolated", source=source)
    assert git(source, "ls-files", "--stage") == before


def test_optional_runtime_is_a_clean_uninitialized_submodule(source):
    oid = git(source, "rev-parse", "HEAD").decode().strip()
    write(source, ".gitmodules", b'[submodule "vendor/runtime"]\n\tpath = vendor/runtime\n\turl = https://example.invalid/runtime.git\n')
    git(source, "update-index", "--add", "--cacheinfo", f"160000,{oid},vendor/runtime")
    destination = source / ".tmp/releases/submodule"
    release.export(destination, source=source)
    assert (destination / "vendor/runtime").is_dir()
    assert not list((destination / "vendor/runtime").iterdir())
    assert not git(destination, "diff", "--name-only").strip()
    assert git(destination, "ls-files", "--stage", "vendor/runtime").startswith(b"160000 ")
