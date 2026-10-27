[CmdletBinding()]
param([string]$Address)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskExe = Join-Path $taskRoot 'data/tools/caddy/2.11.7/caddy.exe'
$taskPrivate = Join-Path $taskRoot 'data/lan-https'
$taskSettings = Join-Path $taskPrivate 'settings.json'
$taskConfig = Join-Path $taskRoot 'config/lan-https.Caddyfile'
$taskConfigHash = (Get-FileHash -LiteralPath $taskConfig -Algorithm SHA256).Hash
if (-not (Test-Path -LiteralPath $taskExe)) { throw 'Run scripts/setup-lan-https.ps1 first.' }
$taskInstall = Get-Content -Raw -LiteralPath (Join-Path (Split-Path $taskExe) 'install.json') | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $taskExe -Algorithm SHA256).Hash -ne $taskInstall.exe_sha256) { throw 'Gateway binary checksum changed.' }
if (-not $Address -and (Test-Path -LiteralPath $taskSettings)) { $Address = (Get-Content -Raw -LiteralPath $taskSettings | ConvertFrom-Json).address }
if (-not $Address) {
    $Address = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -match '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)' -and $_.InterfaceAlias -notmatch 'vEthernet|Loopback' } |
        Sort-Object @{Expression={if ($_.InterfaceAlias -match 'Ethernet') {0} else {1}}} | Select-Object -First 1 -ExpandProperty IPAddress
}
if ($Address -notmatch '^(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})$') { throw 'Choose a private IPv4 LAN address, not a public host.' }
$taskParsed = [Net.IPAddress]::Parse($Address)
if ($taskParsed.ToString() -ne $Address -or -not (Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -eq $Address)) { throw 'The chosen address is not assigned to this computer.' }
New-Item -ItemType Directory -Path $taskPrivate -Force | Out-Null
# The CA signing key must not inherit broad workspace/drive permissions.
$taskSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $taskPrivate '/inheritance:r' '/grant:r' "*${taskSid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not protect the gateway CA directory.' }
$taskListener = Get-NetTCPConnection -LocalPort 3443 -State Listen -ErrorAction SilentlyContinue
$taskAlreadyRunning = $false
if ($taskListener) {
    foreach ($taskPid in ($taskListener.OwningProcess | Select-Object -Unique)) {
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskPid"
        if ($taskProcess.ExecutablePath -ne $taskExe -or $taskProcess.CommandLine -notlike '*lan-https.Caddyfile*') { throw 'Port 3443 belongs to another service; nothing was stopped.' }
    }
    if (-not (Test-Path -LiteralPath $taskSettings) -or (Get-Content -Raw -LiteralPath $taskSettings | ConvertFrom-Json).address -ne $Address) { throw 'The running gateway uses another address. Stop its exact process before changing its binding.' }
    if ((Get-Content -Raw -LiteralPath $taskSettings | ConvertFrom-Json).config_sha256 -ne $taskConfigHash) { throw 'Gateway configuration changed. Stop its exact process and run this script again; live voice sessions would be disconnected.' }
    $taskAlreadyRunning = $true
}
$taskOldData = $env:DARIUS_HTTPS_DATA; $taskOldAddress = $env:DARIUS_LAN_ADDRESS
$taskOldXdgConfig = $env:XDG_CONFIG_HOME; $taskOldXdgData = $env:XDG_DATA_HOME
try {
    $env:DARIUS_HTTPS_DATA = (Join-Path $taskPrivate 'storage').Replace('\','/')
    $env:DARIUS_LAN_ADDRESS = $Address
    $env:XDG_CONFIG_HOME = (Join-Path $taskPrivate 'config').Replace('\','/')
    $env:XDG_DATA_HOME = (Join-Path $taskPrivate 'data').Replace('\','/')
    & $taskExe validate --config $taskConfig --adapter caddyfile
    if ($LASTEXITCODE -ne 0) { throw 'HTTPS gateway configuration failed validation.' }
    [pscustomobject]@{version=1;address=$Address;port=3443;config_sha256=$taskConfigHash} | ConvertTo-Json | Set-Content -LiteralPath $taskSettings -Encoding UTF8
    if (-not $taskAlreadyRunning) {
        $taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $taskProcess = Start-Process -FilePath $taskExe -ArgumentList @('run','--config',('"' + $taskConfig + '"'),'--adapter','caddyfile') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRoot "data/https-$taskStamp.stdout.log") -RedirectStandardError (Join-Path $taskRoot "data/https-$taskStamp.stderr.log") -PassThru
        Write-Host "HTTPS gateway process: $($taskProcess.Id)"
    }
} finally {
    $env:DARIUS_HTTPS_DATA = $taskOldData; $env:DARIUS_LAN_ADDRESS = $taskOldAddress
    $env:XDG_CONFIG_HOME = $taskOldXdgConfig; $env:XDG_DATA_HOME = $taskOldXdgData
}
$taskCaPath = Join-Path $taskPrivate 'storage/pki/authorities/local/root.crt'
$taskReady = $false
for ($taskAttempt=0; $taskAttempt -lt 30; $taskAttempt++) {
    if (Test-Path -LiteralPath $taskCaPath) {
        try { $taskTcp = [Net.Sockets.TcpClient]::new(); $taskTcp.Connect($Address,3443); $taskTcp.Dispose(); $taskReady=$true; break } catch { }
    }
    Start-Sleep -Milliseconds 500
}
if (-not $taskReady) { throw 'HTTPS gateway did not become ready. Check data/https-*.stderr.log.' }
# Export only the public root certificate; never publish a signing/private key.
$taskCa = [Security.Cryptography.X509Certificates.X509Certificate2]::new([IO.File]::ReadAllBytes($taskCaPath))
$taskPublicCa = Join-Path $taskRoot 'apps/web/public/darius-lan-ca.cer'
[IO.File]::WriteAllBytes($taskPublicCa, $taskCa.Export([Security.Cryptography.X509Certificates.X509ContentType]::Cert))
$taskFingerprint = (Get-FileHash -LiteralPath $taskPublicCa -Algorithm SHA256).Hash
$taskInfo = [pscustomobject]@{secure_url="https://${Address}:3443";setup_url="http://${Address}:3000/lan-setup.html";certificate_sha256=$taskFingerprint;certificate_expires=$taskCa.NotAfter.ToUniversalTime().ToString('o')}
$taskInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRoot 'apps/web/public/darius-lan-info.json') -Encoding UTF8
$taskCa.Dispose()
Write-Host "Secure Darius: https://${Address}:3443"
Write-Host "Device setup:  http://${Address}:3000/lan-setup.html"
Write-Host "Public CA certificate SHA-256: $taskFingerprint"
Write-Host 'No device trust stores were changed. Each device must trust this CA and grant microphone permission.'
Write-Host 'If a firewall blocks access, see scripts/enable-lan-https-firewall.ps1 (LAN subnet and port 3443 only).'
