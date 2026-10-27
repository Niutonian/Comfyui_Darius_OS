[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $taskRoot
if (-not (Test-Path -LiteralPath '.venv-pipecat/Scripts/python.exe')) {
    uv venv .venv-pipecat --python 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated Pipecat environment' }
}
uv pip install --python .venv-pipecat/Scripts/python.exe -r apps/voice/requirements-pipecat.txt
if ($LASTEXITCODE -ne 0) { throw 'Could not install Pipecat' }
& .venv-pipecat/Scripts/python.exe scripts/download-pipecat-models.py
if ($LASTEXITCODE -ne 0) { throw 'Could not download Pipecat speech assets' }
Write-Host 'CPU Pipecat installed. The normal Darius launcher will start it on port 8003.'
