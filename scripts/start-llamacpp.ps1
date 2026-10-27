param(
    [string]$Model = "unsloth/Qwen3.5-9B-GGUF:Q6_K",
    [int]$ContextSize = 16384,
    [int]$Port = 8080,
    [string]$ModelPath = "",
    [string]$Alias = "",
    [string]$ServerPath = "",
    [ValidateSet('f16','q8_0')][string]$CacheType = 'f16',
    [int]$MicroBatchSize = 512,
    [int]$ParallelSlots = 0,
    [ValidateSet('none','ngram-cache','draft-mtp','draft-mtp,ngram-cache')][string]$SpecType = 'none',
    [switch]$DisableVision,
    [switch]$DryRun
)

$server = Get-Command $(if ($ServerPath) { $ServerPath } else { 'llama-server' }) -ErrorAction Stop
$modelLabel = if ($Alias) { $Alias } elseif ($ModelPath) { $ModelPath } else { $Model }
Write-Host "Starting llama.cpp model $modelLabel at http://127.0.0.1:$Port"
Write-Host "The model will sleep after one idle second so ComfyUI can reclaim GPU memory."

$llamaArguments = @('--host','127.0.0.1','--port',"$Port",'--jinja','-fa','on','-ngl','99',
    '-c',"$ContextSize",'--temp','0.6','--top-p','0.95','--top-k','20',
    '--reasoning-budget','0','--sleep-idle-seconds','1',
    '--cache-type-k',$CacheType,'--cache-type-v',$CacheType,'-ub',"$MicroBatchSize")
if ($ModelPath) {
    if (!(Test-Path -LiteralPath $ModelPath -PathType Leaf)) { throw "Model file not found: $ModelPath" }
    $llamaArguments += @('-m',(Resolve-Path -LiteralPath $ModelPath).Path)
} else { $llamaArguments += @('-hf',$Model) }
if ($Alias) { $llamaArguments += @('--alias',$Alias) }
if ($ParallelSlots -gt 0) { $llamaArguments += @('--parallel',"$ParallelSlots") }
if ($DisableVision) { $llamaArguments += '--no-mmproj' }
if ($SpecType -ne 'none') { $llamaArguments += @('--spec-type',$SpecType,'--spec-draft-n-max','2') }
if ($DryRun) { $llamaArguments; return }
& $server.Source @llamaArguments
