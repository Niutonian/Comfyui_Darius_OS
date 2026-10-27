[CmdletBinding()]
param(
    [switch]$WithWorker,
    [switch]$Development,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot 'darius-manager-core.ps1')
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$webRoot = Join-Path $repoRoot "apps\web"
$bindHost = "0.0.0.0"
$logRoot = Join-Path $repoRoot "data"
$logTag = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

function Start-DariusService([string]$Name, [string]$Executable, [string]$Directory, [string[]]$Arguments) {
    $stdout = Join-Path $logRoot "$Name-start-$logTag.stdout.log"
    $stderr = Join-Path $logRoot "$Name-start-$logTag.stderr.log"
    Write-Host "$Name logs: $stdout / $stderr"
    # Start-Process joins arrays into one Windows command line. Quote path arguments
    # explicitly so an installation under e.g. "Darius Studio" starts correctly.
    $quotedArguments = $Arguments | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"' }
        else { $_ }
    }
    return Start-Process -FilePath $Executable -WorkingDirectory $Directory -ArgumentList $quotedArguments -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
}

function Wait-DariusReady([string]$Name, [string]$Url, $Process) {
    Write-Host "Waiting for $Name to become ready..."
    $deadline = (Get-Date).AddSeconds(180)
    do {
        $Process.Refresh()
        if ($Process.HasExited) { break }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) { Write-Host "$Name ready."; return }
        } catch { }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    foreach ($suffix in "stderr", "stdout") {
        $logPath = Join-Path $logRoot "$Name-start-$logTag.$suffix.log"
        if (Test-Path -LiteralPath $logPath) { Get-Content -LiteralPath $logPath -Tail 30 | Out-Host }
    }
    throw "$Name did not become ready. See data/$Name-start-$logTag.*.log."
}

function Test-DariusProcess([int]$ProcessId) {
    return @(Get-DariusOwnedProcesses | Where-Object { $_.ProcessId -eq $ProcessId }).Count -gt 0
}

function Stop-DariusListeners {
    # The launcher owns these ports. Only stop listeners whose process lineage
    # belongs to this checkout, so unrelated local services are left alone.
    foreach ($port in 8000, 3000, 3001, 8002, 8003) {
        $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($listener in $listeners) {
            if (Test-DariusProcess $listener.OwningProcess) {
                $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
                Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
                $wrapper = if ($listenerProcess) { Get-CimInstance Win32_Process -Filter "ProcessId = $($listenerProcess.ParentProcessId)" -ErrorAction SilentlyContinue } else { $null }
                if ($wrapper -and $wrapper.Name -match "^(python|node|cmd)\.exe$" -and (Test-DariusProcess $wrapper.ProcessId)) {
                    Stop-Process -Id $listenerProcess.ParentProcessId -Force -ErrorAction SilentlyContinue
                }
            }
        }
    }
    $workers = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "darius_api\.worker" -and (Test-DariusProcess $_.ProcessId) })
    foreach ($workerProcess in $workers) { Stop-Process -Id $workerProcess.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 750
}

Stop-DariusListeners

$lanAddress = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.InterfaceAlias -notmatch "vEthernet|Loopback|Teredo" } |
    Select-Object -First 1 -ExpandProperty IPAddress)
if (-not $lanAddress) { $lanAddress = "localhost" }

if (-not (Test-Path $python)) {
    throw "Python environment not found at $python. Run the README setup first."
}
if (-not (Test-Path (Join-Path $webRoot "node_modules"))) {
    throw "Frontend dependencies are missing. Run npm ci in apps/web first."
}
if (-not $Development -and -not $SkipBuild) {
    Write-Host "Building the web app for LAN access..."
    & npm.cmd run build --prefix $webRoot
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
}
if (-not $Development -and -not (Test-Path -LiteralPath (Join-Path $webRoot ".next\BUILD_ID"))) {
    throw "No production build found. Run without -SkipBuild first."
}

$apiArguments = @("-m", "uvicorn", "darius_api.main:app")
if ($Development) { $apiArguments += @("--reload", "--reload-dir", "apps/api") }
$apiArguments += @("--timeout-graceful-shutdown", "5", "--host", $bindHost, "--port", "8000")
$api = Start-DariusService -Name "api" -Executable $python -Directory $repoRoot -Arguments $apiArguments
Wait-DariusReady -Name "api" -Url "http://127.0.0.1:8000/openapi.json" -Process $api

$webArguments = if ($Development) {
    @((Join-Path $webRoot "node_modules\next\dist\bin\next"), "dev", "--hostname", $bindHost, "--port", "3000")
} else {
    @((Join-Path $webRoot "node_modules\next\dist\bin\next"), "start", "--hostname", $bindHost, "--port", "3000")
}
$web = Start-DariusService -Name "web" -Executable (Get-Command node.exe -ErrorAction Stop).Source -Directory $webRoot -Arguments $webArguments
Wait-DariusReady -Name "web" -Url "http://127.0.0.1:3000" -Process $web

$processes = @($api, $web)
$voicePython = Join-Path $repoRoot ".venv-voice\Scripts\python.exe"
if ((Test-Path -LiteralPath $voicePython) -and (Test-Path -LiteralPath (Join-Path $repoRoot "data\models\voice-manifest.json"))) {
    if (-not (Get-NetTCPConnection -LocalPort 8002 -State Listen -ErrorAction SilentlyContinue)) {
        $voice = Start-DariusService -Name "voice" -Executable $voicePython -Directory $repoRoot -Arguments @(
            "-m", "uvicorn", "apps.voice.server:app", "--host", $bindHost, "--port", "8002",
            "--ws-max-size", "32768", "--ws-max-queue", "32"
        )
        $processes += $voice
    }
    Write-Host "Local wake recognition and OmniVoice: http://${lanAddress}:8002"
}
$pipecatPython = Join-Path $repoRoot '.venv-pipecat\Scripts\python.exe'
if ((Test-Path -LiteralPath $pipecatPython) -and (Test-Path -LiteralPath (Join-Path $repoRoot 'data\models\pipecat\manifest.json'))) {
    if (-not (Get-NetTCPConnection -LocalPort 8003 -State Listen -ErrorAction SilentlyContinue)) {
        $pipecat = Start-DariusService -Name 'pipecat' -Executable $pipecatPython -Directory $repoRoot -Arguments @(
            '-m', 'uvicorn', 'apps.voice.pipecat_server:app', '--host', $bindHost, '--port', '8003',
            '--ws-max-size', '32768', '--ws-max-queue', '16'
        )
        $processes += $pipecat
    }
    Write-Host "Pipecat CPU voice: http://${lanAddress}:8003"
}
if ($WithWorker) {
    $worker = Start-DariusService -Name "worker" -Executable $python -Directory $repoRoot -Arguments @(
        "-m", "darius_api.worker"
    )
    $processes += $worker
}

Write-Host "Darius API ready at http://127.0.0.1:8000 (LAN: http://${lanAddress}:8000)"
Write-Host "Darius web ready at http://127.0.0.1:3000"
Write-Host "Open Darius from another computer at: http://${lanAddress}:3000"
if (Test-Path -LiteralPath (Join-Path $repoRoot 'data/tools/caddy/2.11.7/caddy.exe')) {
    try { & (Join-Path $PSScriptRoot 'start-lan-https.ps1') }
    catch { Write-Warning "LAN HTTPS could not start: $_. Existing localhost/HTTP access remains available." }
}
if ($Development) { Write-Host "Development mode is enabled. Use the default production mode for reliable LAN access." }
if (-not $WithWorker) {
    Write-Host "Persistent general worker not started. Authorized Canvas/local-chat jobs can start workers on demand."
}
Write-Host ("Started process IDs: " + (($processes | ForEach-Object Id) -join ", "))
Write-Host "Stop them with: Stop-Process -Id <pid>"
