# Dot-sourceable operations; loading this file never installs or stops anything.
$script:DariusRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))

function Invoke-DariusCommand([string]$Executable, [string[]]$Arguments) {
    Write-Host ("Running " + [IO.Path]::GetFileName($Executable) + ' ' + ($Arguments -join ' ')) -ForegroundColor Cyan
    & $Executable @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "A setup command failed (exit $LASTEXITCODE). See the log above. Correct the problem and run the action again." }
}

function Update-DariusPath {
    # Preserve session additions; pick up tools installed by WinGet without a reboot.
    $items = @($env:Path, [Environment]::GetEnvironmentVariable('Path', 'Machine'),
        [Environment]::GetEnvironmentVariable('Path', 'User'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'),
        (Join-Path $env:USERPROFILE '.local\bin'))
    $seen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $env:Path = ((($items -join ';') -split ';') | Where-Object {
        $_ -and $seen.Add($_)
    }) -join ';'
}

function Get-DariusOwnedProcesses {
    # Exact executable/entrypoint matching. A nested checkout is a different app.
    $pythonPaths = @('.venv', '.venv-voice', '.venv-pipecat') | ForEach-Object {
        Join-Path $script:DariusRoot "$_\Scripts\python.exe"
    }
    $nextPath = [regex]::Escape((Join-Path $script:DariusRoot 'apps\web\node_modules\next\dist\bin\next'))
    $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $byId = @{}
    foreach ($item in $all) { $byId[$item.ProcessId] = $item }
    $all | Where-Object {
        $parent = $byId[$_.ParentProcessId]
        ($_.ExecutablePath -and ($pythonPaths -contains $_.ExecutablePath)) -or
        ($_.Name -eq 'python.exe' -and $parent -and ($pythonPaths -contains $parent.ExecutablePath)) -or
        ($_.Name -eq 'node.exe' -and ($_.CommandLine -replace '/', '\') -match ('(?:"|\s)' + $nextPath + '(?:"|\s|$)'))
    }
}

function Assert-DariusStopped {
    if (@(Get-DariusOwnedProcesses).Count) {
        throw 'Darius is running in this folder. Finish any generation, then use Stop Darius before installing, repairing or updating.'
    }
}

function Assert-DariusPortsFree {
    foreach ($port in 3000, 8000, 8002, 8003) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw "Port $port is already in use. No service was stopped. Close the other instance or use its existing browser window."
        }
    }
}

function Install-DariusTool([string]$Command, [string]$Package) {
    if (Get-Command $Command -ErrorAction SilentlyContinue) { return }
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw 'Windows App Installer (WinGet) is missing. Install it from Microsoft Store, reopen this manager, and retry. Alternatively install uv, Node.js LTS, Git and FFmpeg yourself.'
    }
    Write-Host "Installing $Package through Windows Package Manager. Windows may request permission."
    Invoke-DariusCommand 'winget.exe' @('install', '--exact', '--id', $Package, '--source', 'winget',
        '--accept-package-agreements', '--accept-source-agreements')
    Update-DariusPath
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "$Package was installed but is not available in this session. Close the manager, reopen it and retry."
    }
}

function Initialize-DariusUv {
    $minimum = [version]'0.11.19'
    if (Get-Command uv.exe -ErrorAction SilentlyContinue) {
        $reported = (& uv.exe --version | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $reported -match '^uv (\d+\.\d+\.\d+)(?:\s|$)' -and [version]$Matches[1] -ge $minimum) {
            Write-Host "Using $reported"
            return
        }
        Write-Host 'The existing uv is below this release minimum supported version. Preparing a compatible private copy; your system uv will not be changed.'
    }
    $architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($architecture -eq 'ARM64') {
        $target = 'aarch64-pc-windows-msvc'
        $expected = '3248109afad3ec59baad299d324ff53de17e2d9a3b3e21580ffd26744b11e036'
    } elseif ([Environment]::Is64BitOperatingSystem) {
        $target = 'x86_64-pc-windows-msvc'
        $expected = '0a23463216d09c6a72ff80ef5dc5a795f07dc1575cb84d24596c2f124a441b7b'
    } else { throw 'The Darius installer requires 64-bit Windows.' }
    $tools = Join-Path $script:DariusRoot "data\tools\uv\0.11.28\$target"
    New-Item -ItemType Directory -Path $tools -Force | Out-Null
    $executable = Join-Path $tools 'uv.exe'
    if (-not (Test-Path -LiteralPath $executable)) {
        $archive = Join-Path $tools 'uv.zip'
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Write-Host 'Downloading uv 0.11.28 from the official Astral release (checksum verified).'
        Invoke-WebRequest -Uri "https://github.com/astral-sh/uv/releases/download/0.11.28/uv-$target.zip" -OutFile $archive -UseBasicParsing -TimeoutSec 180
        $sha = [Security.Cryptography.SHA256]::Create()
        $stream = [IO.File]::OpenRead($archive)
        try { $actual = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
        finally { $stream.Dispose(); $sha.Dispose() }
        if ($actual -ne $expected) { throw 'uv download checksum mismatch. The downloaded program will not be run.' }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $bundle = [IO.Compression.ZipFile]::OpenRead($archive)
        try {
            $entry = $bundle.GetEntry('uv.exe')
            if (-not $entry) { throw 'Official uv archive has an unexpected layout.' }
            $temporary = Join-Path $tools 'uv.new.exe'
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $temporary, $true)
            Move-Item -LiteralPath $temporary -Destination $executable -Force
        } finally { $bundle.Dispose() }
    }
    $reported = (& $executable --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $reported -notmatch '^uv 0\.11\.28(?:\s|$)') { throw 'The private uv executable failed its version check. No dependency changes were attempted.' }
    $env:Path = $tools + ';' + $env:Path
    Write-Host "Using private $reported"
}

function Initialize-DariusConfiguration {
    foreach ($pair in @(@('.env.example', '.env'), @('apps\web\.env.example', 'apps\web\.env.local'))) {
        $target = Join-Path $script:DariusRoot $pair[1]
        if (-not (Test-Path -LiteralPath $target)) {
            Copy-Item -LiteralPath (Join-Path $script:DariusRoot $pair[0]) -Destination $target
        }
    }
}

function Backup-DariusInstallation([switch]$SettingsOnly) {
    Assert-DariusStopped
    $backup = Join-Path $script:DariusRoot ('data\backups\setup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    foreach ($file in '.env', 'apps\web\.env.local') {
        $path = Join-Path $script:DariusRoot $file
        if (Test-Path -LiteralPath $path) {
            $name = if ($file -eq '.env') { 'backend.env' } else { 'frontend.env' }
            Copy-Item -LiteralPath $path -Destination (Join-Path $backup $name)
        }
    }
    $python = Join-Path $script:DariusRoot '.venv\Scripts\python.exe'
    if ($SettingsOnly) {
        [IO.File]::WriteAllText((Join-Path $backup 'BACKUP_REPORT.txt'), "Private settings-only backup. Do not share.`r`nDatabase, media, workflows and external dependencies are not included in this early setup backup.`r`nA verified database/workflow backup follows successful dependency installation before migration.")
        # A failed first sync may have created Python without SQLAlchemy yet.
        # Back up settings now; the full configured database backup follows sync,
        # before any migrations. Sync itself never migrates the database.
    } elseif (Test-Path -LiteralPath $python) {
        Invoke-DariusCommand $python @((Join-Path $script:DariusRoot 'scripts\backup-installation.py'), $backup)
    } elseif (Test-Path -LiteralPath (Join-Path $script:DariusRoot 'data\darius.db')) {
        throw 'An existing database has no working Python environment. Restore the environment or make a verified database backup before repairing.'
    }
    Write-Host "Private backup: $backup (contains settings; do not share)."
    if (-not $SettingsOnly -and (Test-Path -LiteralPath (Join-Path $backup "BACKUP_REPORT.txt"))) { Get-Content -LiteralPath (Join-Path $backup "BACKUP_REPORT.txt") | Out-Host }
}

function Install-DariusComfyCli {
    $cliEnvironment = Join-Path $script:DariusRoot 'data\tools\comfy-cli\1.17.0\venv'
    $cliPython = Join-Path $cliEnvironment 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $cliPython)) {
        Invoke-DariusCommand 'uv.exe' @('venv', $cliEnvironment, '--python', '3.12')
    }
    Invoke-DariusCommand 'uv.exe' @('pip', 'install', '--python', $cliPython, '--reinstall-package', 'comfy-cli', 'comfy-cli==1.17.0')
}

function Repair-DariusBackend {
    Assert-DariusStopped
    if (-not (Test-Path -LiteralPath (Join-Path $script:DariusRoot 'data\installation.json')) -or
        -not (Test-Path -LiteralPath (Join-Path $script:DariusRoot 'apps\web\.next\BUILD_ID'))) {
        throw 'No completed installation/build was found. Open install.bat and use Install / repair first.'
    }
    Initialize-DariusUv
    Backup-DariusInstallation -SettingsOnly
    Invoke-DariusCommand 'uv.exe' @('sync', '--frozen', '--extra', 'test', '--python', '3.12')
    Backup-DariusInstallation
    Invoke-DariusCommand (Join-Path $script:DariusRoot '.venv\Scripts\python.exe') @('-m', 'alembic', 'upgrade', 'head')
    Write-Host 'Backend repaired. The existing web build is retained. Start Darius from the manager.'
}

function Get-DariusOllamaExecutable {
    $command = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source) { return $command.Source }
    $standard = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path -LiteralPath $standard -PathType Leaf) { return $standard }
    return $null
}

function Get-DariusOllamaApiState([string]$Python, [string]$Helper, [switch]$Quiet) {
    if ($Quiet) { & $Python $Helper probe | Out-Null }
    else { & $Python $Helper probe | Out-Host }
    return $LASTEXITCODE
}

function Install-DariusOllama {
    Assert-DariusStopped
    $python = Join-Path $script:DariusRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath (Join-Path $script:DariusRoot 'data\installation.json'))) {
        throw 'Run Install / repair first, then choose Install local AI. Ollama is optional and is not part of the main installation.'
    }
    Write-Host 'Optional local AI: Ornith 1.5 9B Q4_K_M, about 6.6 GB of model downloads.'
    Write-Host 'Allow additional space for Ollama itself. 16 GB or more system RAM is recommended; CPU-only operation can be slow. GPU speed depends on available VRAM. No chat inference is run by setup.'
    try {
        $memory = (Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).TotalPhysicalMemory
        if ($memory) { Write-Host ('Detected system RAM: {0:N1} GB' -f ($memory / 1GB)) }
    } catch { Write-Host 'RAM could not be detected. Check hardware requirements in the Ollama setup guide.' }
    $helper = Join-Path $PSScriptRoot 'setup-ollama.py'
    $probe = Get-DariusOllamaApiState $python $helper
    if ($probe -notin @(0, 3)) { throw 'The service on port 11434 could not be verified as local Ollama. No application was installed or started; check the service and retry.' }
    if ($probe -eq 3) {
        $executable = Get-DariusOllamaExecutable
        if (-not $executable) {
            if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
                throw 'WinGet is unavailable. Install Ollama from https://ollama.com/download/windows, then run Install local AI again. No provider settings were changed.'
            }
            Write-Host 'Installing the official per-user Ollama package through WinGet. Existing Ollama installations and models are reused.'
            Invoke-DariusCommand 'winget.exe' @('install', '--exact', '--id', 'Ollama.Ollama', '--source', 'winget',
                '--scope', 'user', '--accept-package-agreements', '--accept-source-agreements')
            Update-DariusPath
            $executable = Get-DariusOllamaExecutable
            if (-not $executable) { throw 'Ollama was installed but its executable could not be found. Reopen the manager and run Install local AI again.' }
        } else { Write-Host 'Existing Ollama installation found; it will not be upgraded or replaced.' }
        $probe = Get-DariusOllamaApiState $python $helper
    } else { Write-Host 'Existing local Ollama API found; reusing it without installing another copy.' }
    if ($probe -eq 3) {
        $logs = Join-Path $script:DariusRoot 'data\setup-logs'
        New-Item -ItemType Directory -Path $logs -Force | Out-Null
        $name = 'ollama-serve-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
        # Restrict only this new child to the native local endpoint. Preserve
        # user/system environment variables and the user's model storage folder.
        $previousHost = [Environment]::GetEnvironmentVariable('OLLAMA_HOST', 'Process')
        try {
            $env:OLLAMA_HOST = '127.0.0.1:11434'
            $started = Start-Process -FilePath $executable -ArgumentList 'serve' -WorkingDirectory $script:DariusRoot -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $logs "$name.out.log") -RedirectStandardError (Join-Path $logs "$name.err.log")
        } finally { [Environment]::SetEnvironmentVariable('OLLAMA_HOST', $previousHost, 'Process') }
        Write-Host 'Waiting for local Ollama. Its startup logs are in data\setup-logs.'
        $deadline = (Get-Date).AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 500
            $probe = Get-DariusOllamaApiState $python $helper -Quiet
        } while ($probe -eq 3 -and (Get-Date) -lt $deadline)
    }
    if ($probe -ne 0) { throw 'Ollama API verification failed. Check data\setup-logs and Ollama logs, then retry. No other service was stopped and your chat provider was not changed.' }
    Invoke-DariusCommand $python @($helper, 'prepare')
    Write-Host 'Optional local AI is ready. Existing chat provider retained until you explicitly select Ornith.'
}

function Select-DariusOllama {
    Assert-DariusStopped
    Backup-DariusInstallation
    Invoke-DariusCommand (Join-Path $script:DariusRoot '.venv\Scripts\python.exe') @((Join-Path $PSScriptRoot 'setup-ollama.py'), 'select')
}

function Install-DariusCore {
    Assert-DariusStopped
    Initialize-DariusUv
    Install-DariusTool 'node.exe' 'OpenJS.NodeJS.LTS'
    Install-DariusTool 'git.exe' 'Git.Git'
    Install-DariusTool 'ffmpeg.exe' 'Gyan.FFmpeg'
    if (-not (Get-Command ffprobe.exe -ErrorAction SilentlyContinue)) { throw 'FFprobe is missing. Install a complete FFmpeg build and retry.' }
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'npm is missing. Repair the Node.js LTS installation and retry.' }
    $version = (& node.exe --version).TrimStart('v') -as [version]
    if (-not $version -or $version -lt [version]'20.9') { throw 'Node.js is too old. Install Node.js LTS, reopen the manager and retry.' }
    Backup-DariusInstallation -SettingsOnly
    Initialize-DariusConfiguration
    Invoke-DariusCommand 'uv.exe' @('python', 'install', '3.12')
    Invoke-DariusCommand 'uv.exe' @('sync', '--frozen', '--extra', 'test', '--python', '3.12')
    # A first install can point at an existing custom database even though it had
    # no Python environment. Resolve that configuration before any migrations too.
    Backup-DariusInstallation
    Install-DariusComfyCli
    Invoke-DariusCommand 'npm.cmd' @('ci', '--no-fund', '--fetch-retries=2', '--fetch-timeout=60000', '--prefix', (Join-Path $script:DariusRoot 'apps\web'))
    Invoke-DariusCommand (Join-Path $script:DariusRoot '.venv\Scripts\python.exe') @('-m', 'alembic', 'upgrade', 'head')
    Invoke-DariusCommand 'npm.cmd' @('run', 'build', '--prefix', (Join-Path $script:DariusRoot 'apps\web'))
    # Written only after all steps succeed. Repair can safely resume a partial install.
    @{ completed = (Get-Date).ToString('o'); version = 1 } | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $script:DariusRoot 'data\installation.json') -Encoding UTF8
    Write-Host 'Installation complete. Configure your AI provider in Settings and your ComfyUI paths in Configuration, then Start Darius.'
}

function Update-DariusInstallation {
    Assert-DariusStopped
    if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { throw 'Git is required for updates. Run Install / repair first.' }
    $top = & git.exe rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0 -or [IO.Path]::GetFullPath($top) -ne $script:DariusRoot) { throw 'This is a source ZIP, not a Git checkout. Extract a newer release into a separate folder and follow the migration guide. No files were replaced.' }
    $dirty = & git.exe status --porcelain --untracked-files=normal
    if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'This checkout has local changes. Update refused; commit or preserve them manually first. Nothing was reset or stashed.' }
    $branch = & git.exe symbolic-ref --quiet --short HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Detached HEAD: switch to your tracked release branch before updating.' }
    $remote = & git.exe config --get "branch.$branch.remote"
    if ($LASTEXITCODE -ne 0 -or -not $remote -or $remote -eq '.' -or $remote.StartsWith('-')) { throw 'No update remote is configured for this branch. No repository URL will be guessed.' }
    $upstream = & git.exe rev-parse --abbrev-ref '@{upstream}' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'No upstream branch is configured. Updates become available after cloning the published repository.' }
    Invoke-DariusCommand 'git.exe' @('fetch', '--prune', $remote)
    # Refuse divergence and local-only commits. This is a release updater, not a merge tool.
    & git.exe merge-base --is-ancestor HEAD '@{upstream}'
    if ($LASTEXITCODE -ne 0) { throw 'Local history diverges from the update branch. No merge, reset or dependency changes were performed.' }
    Backup-DariusInstallation
    Invoke-DariusCommand 'git.exe' @('merge', '--ff-only', '@{upstream}')
    # Re-enter the updated script rather than executing old functions after the pull.
    Invoke-DariusCommand 'powershell.exe' @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $script:DariusRoot 'scripts\darius-manager.ps1'), '-Action', 'Install', '-ParentUpdate')
}

function Get-DariusDiagnostics {
    $checks = foreach ($command in 'uv.exe', 'node.exe', 'npm.cmd', 'git.exe', 'ffmpeg.exe', 'ffprobe.exe') {
        [pscustomobject]@{ Check = $command; Status = $(if (Get-Command $command -ErrorAction SilentlyContinue) { 'Available' } else { 'Missing' }) }
    }
    foreach ($file in '.venv\Scripts\python.exe', 'apps\web\.next\BUILD_ID', '.env', 'apps\web\.env.local') {
        $checks += [pscustomobject]@{ Check = $file; Status = $(if (Test-Path -LiteralPath (Join-Path $script:DariusRoot $file)) { 'Present' } else { 'Missing' }) }
    }
    foreach ($service in @(@('Darius API', 8000, '/openapi.json'), @('Darius web', 3000, '/'), @('ComfyUI', 8188, '/system_stats'))) {
        $status = 'Not reachable'
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$($service[1])$($service[2])" -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) { $status = 'Responding' }
        } catch { }
        $checks += [pscustomobject]@{ Check = $service[0]; Status = $status }
    }
    return $checks
}
