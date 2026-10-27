param(
    [ValidateRange(4096,65536)][int]$ContextSize = 16384,
    [int]$Port = 8080,
    [ValidateSet('none','ngram-cache','draft-mtp','draft-mtp,ngram-cache')][string]$SpecType = 'draft-mtp,ngram-cache',
    [switch]$DryRun
)
$qwenRepoRoot = Split-Path -Parent $PSScriptRoot
$qwenModelPath = Join-Path $qwenRepoRoot 'data\models\llamacpp\Qwen3.8-27B-ByteShape-IQ4_XS-3.84bpw-ASCII-P1M.gguf'
if ($env:LOCALAPPDATA) {
    $qwenCachePath = Join-Path $env:LOCALAPPDATA 'Darius\models\llamacpp\Qwen3.8-27B-ByteShape-IQ4_XS-3.84bpw-ASCII-P1M.gguf'
    if (Test-Path -LiteralPath $qwenCachePath -PathType Leaf) { $qwenModelPath = $qwenCachePath }
}
if (!(Test-Path -LiteralPath $qwenModelPath -PathType Leaf)) { throw 'Run scripts/download-qwen38.py first. The verified GGUF has not finished downloading.' }
if ((Get-Item -LiteralPath $qwenModelPath).Length -ne 12252882720) { throw 'Qwen GGUF has the wrong file size; do not load this partial model.' }
Write-Host 'Qwen 3.8 ASCII profile: English/code only; no vision projector is provided by this repo.'
$qwenServerPath = ''
if ($env:LOCALAPPDATA) {
    $qwenCudaServer = Join-Path $env:LOCALAPPDATA 'Darius\bin\llama-b11015-cuda13.4\llama-server.exe'
    if (Test-Path -LiteralPath $qwenCudaServer -PathType Leaf) { $qwenServerPath = $qwenCudaServer }
}
& (Join-Path $PSScriptRoot 'start-llamacpp.ps1') -ModelPath $qwenModelPath `
    -ServerPath $qwenServerPath `
    -Alias 'islamsidratul/Qwen3.8-27B-ByteShape-IQ4_XS-ASCII-GGUF:IQ4_XS' `
    -ContextSize $ContextSize -Port $Port -CacheType q8_0 -MicroBatchSize 256 `
    -ParallelSlots 1 -SpecType $SpecType -DisableVision -DryRun:$DryRun
