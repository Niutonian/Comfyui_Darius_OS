[CmdletBinding()]
param([switch]$Browser, [switch]$Privacy)
$ErrorActionPreference = "Stop"
$checkRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $checkRoot
try {
    & "$checkRoot/.venv/Scripts/python.exe" -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Backend regressions failed." }
    & "$checkRoot/.venv/Scripts/python.exe" scripts/export_openapi.py --check
    if ($LASTEXITCODE -ne 0) { throw "OpenAPI contract is stale." }
    Push-Location apps/web
    try {
        npm run lint
        if ($LASTEXITCODE -ne 0) { throw "Frontend lint failed." }
        npm run typecheck
        if ($LASTEXITCODE -ne 0) { throw "Frontend typecheck failed." }
        npm test
        if ($LASTEXITCODE -ne 0) { throw "Frontend regressions failed." }
        $previousDist = $env:DARIUS_NEXT_DIST_DIR
        $env:DARIUS_NEXT_DIST_DIR = ".next-check"
        try { npm run build } finally { $env:DARIUS_NEXT_DIST_DIR = $previousDist }
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    } finally { Pop-Location }
    if ($Browser) {
        npm --prefix tests/browser test
        if ($LASTEXITCODE -ne 0) { throw "Browser smoke failed. Run npm ci --prefix tests/browser and npm --prefix tests/browser run install:browser first." }
    }
    if ($Privacy) {
        & "$checkRoot/.venv/Scripts/python.exe" scripts/release_audit.py --history --privacy
        if ($LASTEXITCODE -ne 0) { throw "Publication privacy checks failed. Do not prepare or publish this checkout." }
    }
    Write-Host "Reliability checks passed. No cloud generation or model calls were made."
} finally { Pop-Location }
