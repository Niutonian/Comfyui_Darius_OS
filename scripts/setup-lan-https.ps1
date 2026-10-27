[CmdletBinding()]
param([string]$Address)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskVersion = '2.11.7'
$taskTools = Join-Path $taskRoot "data/tools/caddy/$taskVersion"
$taskExe = Join-Path $taskTools 'caddy.exe'
if (-not (Test-Path -LiteralPath $taskExe)) {
    New-Item -ItemType Directory -Path $taskTools -Force | Out-Null
    $taskAsset = "caddy_${taskVersion}_windows_amd64.zip"
    $taskBase = "https://github.com/caddyserver/caddy/releases/download/v$taskVersion"
    $taskChecksums = (Invoke-WebRequest "$taskBase/caddy_${taskVersion}_checksums.txt" -UseBasicParsing -TimeoutSec 30).Content
    if ($taskChecksums -is [byte[]]) { $taskChecksums = [Text.Encoding]::UTF8.GetString($taskChecksums) }
    $taskLine = ($taskChecksums -split "`n" | Where-Object { ($_ -split '\s+')[-1] -eq $taskAsset })
    if (@($taskLine).Count -ne 1) { throw 'Could not identify the official Caddy checksum.' }
    $taskExpected = ($taskLine.Trim() -split '\s+')[0]
    if ($taskExpected -notmatch '^[0-9a-fA-F]{128}$') { throw 'Invalid official Caddy SHA-512 checksum.' }
    $taskZip = Join-Path $taskTools $taskAsset
    Invoke-WebRequest "$taskBase/$taskAsset" -OutFile $taskZip -UseBasicParsing -TimeoutSec 180
    if ((Get-FileHash -LiteralPath $taskZip -Algorithm SHA512).Hash -ne $taskExpected) { throw 'Caddy checksum mismatch. The archive will not be executed.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $taskArchive = [IO.Compression.ZipFile]::OpenRead($taskZip)
    try {
        $taskEntry = $taskArchive.GetEntry('caddy.exe')
        if (-not $taskEntry) { throw 'The official archive has no caddy.exe.' }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($taskEntry, $taskExe, $false)
    } finally { $taskArchive.Dispose() }
    [pscustomobject]@{version=$taskVersion;source="$taskBase/$taskAsset";archive_sha512=$taskExpected;exe_sha256=(Get-FileHash -LiteralPath $taskExe -Algorithm SHA256).Hash} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskTools 'install.json') -Encoding UTF8
}
$taskInstall = Get-Content -Raw -LiteralPath (Join-Path $taskTools 'install.json') | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $taskExe -Algorithm SHA256).Hash -ne $taskInstall.exe_sha256) { throw 'Installed gateway binary checksum changed. Inspect it before starting.' }
& $taskExe version
if ($LASTEXITCODE -ne 0) { throw 'Caddy could not start.' }
& (Join-Path $PSScriptRoot 'start-lan-https.ps1') -Address $Address
