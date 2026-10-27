[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$voiceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $voiceRoot
if (-not (Test-Path -LiteralPath ".venv-voice\Scripts\python.exe")) {
    uv venv .venv-voice --python 3.12
    if ($LASTEXITCODE -ne 0) { throw "Could not create the voice environment" }
}
uv pip install --python .venv-voice/Scripts/python.exe -r apps/voice/requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Could not install the local speech runtime" }
& .venv-voice/Scripts/python.exe scripts/download-voice-models.py
if ($LASTEXITCODE -ne 0) { throw "Could not download the local voice models" }
Write-Host "Local voice installed. Start Darius to use OmniVoice and wake listening."
