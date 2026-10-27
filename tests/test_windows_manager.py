"""Installer safety checks run in temporary folders, never against live services."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")


def literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def run_ps(script: str) -> subprocess.CompletedProcess[str]:
    if not POWERSHELL:
        pytest.skip("Windows PowerShell required")
    result = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script + "\nexit 0"],
        capture_output=True, text=True, timeout=35,
    )
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    folder = tmp_path / "Darius Studio"
    (folder / "apps/web").mkdir(parents=True)
    (folder / ".env.example").write_text("EXAMPLE=true\n", encoding="utf-8")
    (folder / "apps/web/.env.example").write_text("WEB=true\n", encoding="utf-8")
    return folder


def core(folder: Path) -> str:
    return (
        "$ErrorActionPreference='Stop'; . "
        + literal(ROOT / "scripts/darius-manager-core.ps1")
        + "; $script:DariusRoot=" + literal(folder) + "; "
    )


def test_environment_creation_preserves_existing_settings(checkout: Path):
    secret = b"MY_PRIVATE_SETTING=keep-this\r\n"
    (checkout / ".env").write_bytes(secret)
    run_ps(core(checkout) + "Initialize-DariusConfiguration; Initialize-DariusConfiguration")
    assert (checkout / ".env").read_bytes() == secret
    assert (checkout / "apps/web/.env.local").read_text() == "WEB=true\n"


def test_process_ownership_excludes_other_and_nested_checkouts(checkout: Path):
    output = run_ps(core(checkout) + r"""
        function Get-CimInstance {
            @(
                [pscustomobject]@{ProcessId=1;ParentProcessId=0;Name='python.exe';ExecutablePath="$script:DariusRoot\.venv\Scripts\python.exe";CommandLine='python -m uvicorn'},
                [pscustomobject]@{ProcessId=2;ParentProcessId=1;Name='python.exe';ExecutablePath='C:\Python\python.exe';CommandLine='python -m uvicorn'},
                [pscustomobject]@{ProcessId=3;ParentProcessId=0;Name='python.exe';ExecutablePath="$script:DariusRoot\nested\.venv\Scripts\python.exe";CommandLine='python -m uvicorn'},
                [pscustomobject]@{ProcessId=4;ParentProcessId=0;Name='node.exe';ExecutablePath='C:\node.exe';CommandLine=('node "' + $script:DariusRoot + '\apps\web\node_modules\next\dist\bin\next" start')},
                [pscustomobject]@{ProcessId=5;ParentProcessId=0;Name='node.exe';ExecutablePath='C:\node.exe';CommandLine=('node "' + $script:DariusRoot + '\nested\apps\web\node_modules\next\dist\bin\next" start')}
            )
        }
        @(Get-DariusOwnedProcesses | ForEach-Object ProcessId) | ConvertTo-Json -Compress
    """)
    assert json.loads(output.stdout) == [1, 2, 4]


def test_install_refuses_running_app_before_any_changes(checkout: Path):
    output = run_ps(core(checkout) + """
        function Get-DariusOwnedProcesses { [pscustomobject]@{ProcessId=123} }
        function Install-DariusTool { throw 'MUST NOT INSTALL' }
        try { Install-DariusCore; throw 'Expected refusal' }
        catch { if ($_.Exception.Message -notlike 'Darius is running*') { throw }; 'refused' }
    """)
    assert "refused" in output.stdout
    assert not (checkout / ".env").exists()


def test_update_refuses_dirty_checkout_without_fetch_or_reset(checkout: Path):
    run_ps(core(checkout) + "Set-Location -LiteralPath " + literal(checkout) + "; " + r"""
        function Get-DariusOwnedProcesses { }
        function git.exe {
            if ($args[0] -eq 'rev-parse') { $script:DariusRoot }
            elseif ($args[0] -eq 'status') { ' M README.md' }
            else { throw 'MUST NOT FETCH OR RESET' }
            $global:LASTEXITCODE=0
        }
        try { Update-DariusInstallation; throw 'Expected refusal' }
        catch { if ($_.Exception.Message -notlike '*local changes*') { throw } }
    """)
    assert not (checkout / "data").exists()


def test_install_failure_leaves_no_success_marker_and_retry_completes(checkout: Path):
    (checkout / ".env").write_text("KEEP=yes\n")
    output = run_ps(core(checkout) + r"""
        function Get-DariusOwnedProcesses { }
        function Install-DariusTool { }
        function Initialize-DariusUv { }
        function Backup-DariusInstallation { New-Item -ItemType Directory -Path (Join-Path $script:DariusRoot 'data') -Force | Out-Null }
        function node.exe { 'v22.20.0' }
        function npm.cmd { }
        function ffprobe.exe { }
        $script:fail=$true
        function Invoke-DariusCommand {
            param($Executable, $Arguments)
            if ($script:fail -and $Arguments -contains 'alembic') { throw 'simulated migration failure' }
        }
        try { Install-DariusCore; throw 'Expected failure' }
        catch { if ($_.Exception.Message -ne 'simulated migration failure') { throw } }
        if (Test-Path -LiteralPath (Join-Path $script:DariusRoot 'data\installation.json')) { throw 'Premature success marker' }
        $script:fail=$false
        Install-DariusCore
    """)
    assert "Installation complete" in output.stdout
    assert (checkout / "data/installation.json").exists()
    assert (checkout / ".env").read_text() == "KEEP=yes\n"


def test_occupied_port_is_never_stopped(checkout: Path):
    run_ps(core(checkout) + """
        function Get-NetTCPConnection { [pscustomobject]@{OwningProcess=99} }
        function Stop-Process { throw 'MUST NOT STOP' }
        try { Assert-DariusPortsFree; throw 'Expected refusal' }
        catch { if ($_.Exception.Message -notlike 'Port 3000 is already in use*') { throw } }
    """)


def test_backend_repair_keeps_the_existing_web_build_and_settings(checkout: Path):
    (checkout / 'data').mkdir()
    (checkout / 'data/installation.json').write_text('{}')
    (checkout / 'apps/web/.next').mkdir()
    (checkout / 'apps/web/.next/BUILD_ID').write_text('retain-this-build')
    (checkout / '.env').write_text('KEEP=yes\n')
    run_ps(core(checkout) + """
        function Get-DariusOwnedProcesses { }
        function Initialize-DariusUv { }
        function Backup-DariusInstallation { }
        function Invoke-DariusCommand {
            param($Executable, $Arguments)
            if ($Executable -like '*npm*' -or $Arguments -contains 'build') { throw 'Must retain the web build' }
        }
        Repair-DariusBackend
    """)
    assert (checkout / 'apps/web/.next/BUILD_ID').read_text() == 'retain-this-build'
    assert (checkout / '.env').read_text() == 'KEEP=yes\n'


def test_refreshing_tool_path_does_not_grow_it_on_every_step(checkout: Path):
    run_ps(core(checkout) + """
        Update-DariusPath
        $first=$env:Path
        1..6 | ForEach-Object { Update-DariusPath }
        if ($first -cne $env:Path) { throw 'PATH grew during repeated setup steps' }
    """)


def test_compatible_uv_does_not_download_or_replace_system_tools(checkout: Path):
    run_ps(core(checkout) + """
        function uv.exe { $global:LASTEXITCODE=0; 'uv 0.11.28 (test)' }
        function Invoke-WebRequest { throw 'MUST NOT DOWNLOAD' }
        Initialize-DariusUv
    """)
    assert not (checkout / 'data').exists()


def test_old_uv_download_with_wrong_checksum_is_never_executed(checkout: Path):
    run_ps(core(checkout) + """
        function uv.exe { $global:LASTEXITCODE=0; 'uv 0.5.14 (test)' }
        function Invoke-WebRequest {
            param($Uri, $OutFile)
            [IO.File]::WriteAllText($OutFile, 'invalid archive')
        }
        try { Initialize-DariusUv; throw 'Expected checksum failure' }
        catch { if ($_.Exception.Message -notlike 'uv download checksum mismatch*') { throw } }
    """)
    assert not list((checkout / 'data/tools').rglob('uv.exe'))


def test_partial_environment_can_back_up_settings_before_resuming_sync(checkout: Path):
    (checkout / '.venv/Scripts').mkdir(parents=True)
    (checkout / '.venv/Scripts/python.exe').write_bytes(b'not a working environment yet')
    (checkout / '.env').write_text('KEEP=yes\n')
    run_ps(core(checkout) + """
        function Get-DariusOwnedProcesses { }
        function Invoke-DariusCommand { throw 'MUST NOT IMPORT UNINSTALLED PACKAGES' }
        Backup-DariusInstallation -SettingsOnly
    """)
    saved = list((checkout / 'data/backups').glob('*/backend.env'))
    assert len(saved) == 1
    assert saved[0].read_text() == 'KEEP=yes\n'


def test_powershell_scripts_parse():
    for filename in ("darius-manager.ps1", "darius-manager-core.ps1", "start-local.ps1"):
        run_ps("$errors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
               + literal(ROOT / "scripts" / filename)
               + ", [ref]$null, [ref]$errors); if ($errors) { throw ($errors | Out-String) }")


def ollama_ready(folder):
    (folder / '.venv/Scripts').mkdir(parents=True)
    (folder / '.venv/Scripts/python.exe').write_bytes(b'not executed in this test')
    (folder / 'data').mkdir()
    (folder / 'data/installation.json').write_text('{}')
    (folder / '.env').write_text('KEEP=private\nDARIUS_LLM_PROVIDER=openai\n')


def test_optional_ollama_reuses_running_api_and_does_not_select_provider(checkout):
    ollama_ready(checkout)
    run_ps(core(checkout) + """
        function Get-DariusOwnedProcesses { }
        function Get-CimInstance { [pscustomobject]@{TotalPhysicalMemory=17179869184} }
        function Get-DariusOllamaApiState { return 0 }
        function Get-DariusOllamaExecutable { throw 'Must reuse running API without requiring executable' }
        function Start-Process { throw 'Must not start another server' }
        function Select-DariusOllama { throw 'Must not change provider' }
        $script:prepared=$false
        function Invoke-DariusCommand {
            param($Executable, $Arguments)
            if ($Executable -eq 'winget.exe' -or $Arguments[-1] -ne 'prepare') { throw 'Unexpected install or selection' }
            $script:prepared=$true
        }
        Install-DariusOllama
        if (-not $script:prepared) { throw 'No verification requested' }
    """)
    assert (checkout / '.env').read_text() == 'KEEP=private\nDARIUS_LLM_PROVIDER=openai\n'


def test_optional_ollama_refuses_to_install_over_unverified_listener(checkout):
    ollama_ready(checkout)
    run_ps(core(checkout) + """
        function Get-DariusOwnedProcesses { }
        function Get-CimInstance { }
        function Get-DariusOllamaApiState { return 1 }
        function Get-DariusOllamaExecutable { throw 'Must not install' }
        function Start-Process { throw 'Must not start' }
        try { Install-DariusOllama; throw 'Expected refusal' }
        catch { if ($_.Exception.Message -notlike '*No application was installed or started*') { throw } }
    """)


def test_optional_ollama_installs_only_missing_official_user_package(checkout):
    ollama_ready(checkout)
    run_ps(core(checkout) + """
        function Get-DariusOwnedProcesses { }
        function Get-CimInstance { }
        $script:probe=0; $script:found=0; $script:installed=$false; $script:prepared=$false
        function Get-DariusOllamaApiState { $script:probe++; if ($script:probe -eq 1) { return 3 }; return 0 }
        function Get-DariusOllamaExecutable { $script:found++; if ($script:found -gt 1) { return 'fake-ollama.exe' } }
        function winget.exe { throw 'Must be intercepted before real package invocation' }
        function Update-DariusPath { }
        function Start-Process { throw 'Installer already started the verified server' }
        function Invoke-DariusCommand {
            param($Executable, $Arguments)
            if ($Executable -eq 'winget.exe') {
                if ($Arguments -notcontains 'Ollama.Ollama' -or $Arguments -notcontains 'user') { throw 'Wrong package or scope' }
                $script:installed=$true
            } elseif ($Arguments[-1] -eq 'prepare') { $script:prepared=$true }
            else { throw 'Unexpected command' }
        }
        Install-DariusOllama
        if (-not $script:installed -or -not $script:prepared) { throw 'Missing installation or verification' }
    """)


def test_optional_ollama_starts_only_missing_daemon_hidden_and_restores_environment(checkout):
    ollama_ready(checkout)
    run_ps(core(checkout) + """
        function Get-DariusOwnedProcesses { }
        function Get-CimInstance { }
        function Get-DariusOllamaExecutable { return 'fake-ollama.exe' }
        $script:probe=0; $script:started=$false
        function Get-DariusOllamaApiState { $script:probe++; if ($script:probe -lt 3) { return 3 }; return 0 }
        function Start-Sleep { }
        function Start-Process {
            param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$PassThru, $RedirectStandardOutput, $RedirectStandardError)
            if ($FilePath -ne 'fake-ollama.exe' -or $WindowStyle -ne 'Hidden' -or $ArgumentList -ne 'serve') { throw 'Unexpected launch' }
            if ($env:OLLAMA_HOST -ne '127.0.0.1:11434') { throw 'Wrong child endpoint' }
            $script:started=$true
        }
        function Invoke-DariusCommand {
            param($Executable, $Arguments)
            if ($Executable -eq 'winget.exe' -or $Arguments[-1] -ne 'prepare') { throw 'Must not install or select' }
        }
        $env:OLLAMA_HOST='original-setting'
        Install-DariusOllama
        if (-not $script:started -or $env:OLLAMA_HOST -ne 'original-setting') { throw 'Server not started or user environment changed' }
    """)


def test_optional_ollama_requires_main_install_and_stopped_app(checkout):
    run_ps(core(checkout) + """
        function Get-DariusOwnedProcesses { }
        function Get-DariusOllamaApiState { throw 'Must not contact API' }
        try { Install-DariusOllama; throw 'Expected prerequisite refusal' }
        catch { if ($_.Exception.Message -notlike '*Run Install / repair first*') { throw } }
        function Get-DariusOwnedProcesses { [pscustomobject]@{ProcessId=123} }
        try { Install-DariusOllama; throw 'Expected running-app refusal' }
        catch { if ($_.Exception.Message -notlike '*Darius is running*') { throw } }
    """)


def test_ollama_selection_backs_up_before_running_explicit_selection(checkout):
    run_ps(core(checkout) + """
        function Get-DariusOwnedProcesses { }
        $script:backed=$false
        function Backup-DariusInstallation { $script:backed=$true }
        function Invoke-DariusCommand {
            param($Executable, $Arguments)
            if (-not $script:backed -or $Arguments[-1] -ne 'select') { throw 'Selection must follow backup' }
        }
        Select-DariusOllama
    """)


def test_database_backup_uses_configured_database_and_includes_wal(tmp_path: Path, monkeypatch):
    spec = importlib.util.spec_from_file_location("installer_backup", ROOT / "scripts/backup-installation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    database = tmp_path / "custom.db"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE ideas (name TEXT)")
        connection.execute("INSERT INTO ideas VALUES ('keep me')")
        connection.commit()
        monkeypatch.setattr(module, "Settings", SimpleNamespace(from_env=lambda: SimpleNamespace(database_url=f"sqlite:///{database.as_posix()}")))
        module.backup(tmp_path / "backup")
    with sqlite3.connect(tmp_path / "backup/darius.db") as result:
        assert result.execute("SELECT name FROM ideas").fetchall() == [("keep me",)]


def test_external_database_refuses_automatic_migration_backup(tmp_path: Path, monkeypatch):
    spec = importlib.util.spec_from_file_location("installer_backup", ROOT / "scripts/backup-installation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "Settings", SimpleNamespace(from_env=lambda: SimpleNamespace(database_url="postgresql://localhost/darius")))
    with pytest.raises(RuntimeError, match="external database"):
        module.backup(tmp_path)
