[CmdletBinding()]
param([switch]$Browser, [string]$PlaywrightModule, [string]$UiUrl = "http://127.0.0.1:3000")
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
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    } finally { Pop-Location }
    if ($Browser) {
        if (-not (Test-Path (Join-Path $checkRoot "scripts/check-ui.cjs"))) {
            throw "Browser checks require the workstation-only scripts/check-ui.cjs probe; it is not shipped in source releases. Core checks have passed."
        }
        $env:DARIUS_UI_URL = $UiUrl
        if ($PlaywrightModule) { $env:DARIUS_PLAYWRIGHT_MODULE = $PlaywrightModule }
        node scripts/check-ui.cjs
        if ($LASTEXITCODE -ne 0) { throw "Browser regressions failed." }
    }
    Write-Host "Reliability checks passed. No cloud generation or model calls were made."
} finally { Pop-Location }
