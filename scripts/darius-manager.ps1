[CmdletBinding()]
param(
    [ValidateSet('Menu', 'Install', 'BackendRepair', 'Start', 'Stop', 'Update', 'Diagnostics', 'ConsoleCode', 'Voice', 'Ollama', 'Lan', 'Configuration', 'Logs')]
    [string]$Action = 'Menu',
    [switch]$ParentUpdate,
    [switch]$InteractiveAction,
    [switch]$SelectOllama,
    [string]$PreviewPath
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'darius-manager-core.ps1')
Set-Location -LiteralPath $script:DariusRoot
Update-DariusPath

if ($Action -eq 'Menu') {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()
    $form = New-Object Windows.Forms.Form
    $form.Text = 'Darius | Setup & services'
    $form.ClientSize = New-Object Drawing.Size(620, 632)
    $form.MinimumSize = $form.Size
    $form.StartPosition = 'CenterScreen'
    $form.BackColor = [Drawing.Color]::FromArgb(25, 39, 33)
    $form.ForeColor = [Drawing.Color]::FromArgb(235, 241, 226)
    $form.Font = New-Object Drawing.Font('Segoe UI', 10)
    $heading = New-Object Windows.Forms.Label
    $heading.Text = "Darius`r`nYour creative workspace, ready to run."
    $heading.Font = New-Object Drawing.Font('Segoe UI', 16)
    $heading.SetBounds(26, 22, 560, 70)
    $form.Controls.Add($heading)
    $hint = New-Object Windows.Forms.Label
    $hint.Text = "First time? Install / repair, configure your services, then Start.`r`nEach action opens a progress window. Leave it open until complete."
    $hint.SetBounds(28, 98, 560, 50)
    $form.Controls.Add($hint)
    $actions = @(
        @('Install', 'Install / repair', 'Python 3.12, packages, media tools & web build'),
        @('Start', 'Start Darius', 'Open your workspace in the browser'),
        @('Stop', 'Stop Darius', 'Finish renders first; stops only this installation'),
        @('Update', 'Update Darius', 'Clean Git checkout only; backup + fast-forward'),
        @('Diagnostics', 'Check installation', 'Tools, build, API, website & local ComfyUI'),
        @('ConsoleCode', 'Console code', 'Open or reset this installation''s local access code'),
        @('Configuration', 'Configuration', 'Edit local service paths and backend settings'),
        @('Voice', 'Install CPU voice', 'Optional Pipecat environment & speech models'),
        @('Ollama', 'Install local AI', 'Optional Ollama + Ornith 1.5 9B (~6.6 GB)'),
        @('Lan', 'Set up LAN HTTPS', 'Optional trusted access for phone microphones'),
        @('Logs', 'Open logs', 'Private local logs and installation backups')
    )
    $form.ClientSize = New-Object Drawing.Size(620, (212 + 42 * $actions.Count))
    $form.MinimumSize = $form.Size
    for ($i = 0; $i -lt $actions.Count; $i++) {
        $button = New-Object Windows.Forms.Button
        $button.Text = $actions[$i][1]
        $button.Tag = $actions[$i][0]
        $button.SetBounds(28, (162 + 42 * $i), 205, 34)
        $button.FlatStyle = 'Flat'
        $button.BackColor = [Drawing.Color]::FromArgb(213, 234, 171)
        $button.ForeColor = [Drawing.Color]::FromArgb(27, 42, 30)
        $button.Add_Click({
            $selected = $this.Tag
            if ($selected -in @('Stop', 'Update', 'Install', 'Voice', 'Ollama', 'Lan')) {
                $message = switch ($selected) {
                    'Stop' { 'Finish any active generation first. Stop this Darius installation now?' }
                    'Update' { 'Update from the configured Git upstream, then install dependencies? Local settings and the database are backed up. Darius must be stopped.' }
                    'Install' { 'Install missing Windows tools through WinGet, Python 3.12 and locked Darius packages? Internet access is required; Windows may request permission. Existing settings and projects are preserved. Darius must be stopped.' }
                    'Voice' { 'Download CPU speech models and install an isolated Pipecat environment? Darius must be stopped. This can take several minutes.' }
                    'Ollama' { 'Install missing Ollama and download Ornith 1.5 9B Q4_K_M (about 6.6 GB, plus Ollama application space)? Existing installations and model files are reused. 16 GB or more RAM is recommended; CPU-only chat can be slow. You can choose whether to switch chat after verification. Darius must be stopped.' }
                    'Lan' { 'Download Caddy and configure trusted LAN HTTPS? Darius must be stopped. Other devices will need to trust this machine certificate.' }
                }
                if ([Windows.Forms.MessageBox]::Show($message, 'Darius', 'OKCancel', 'Information') -ne 'OK') { return }
            }
            # Explicitly requested interactive progress window. Paths remain quoted, never evaluated as code.
            Start-Process powershell.exe -WorkingDirectory $script:DariusRoot -ArgumentList @(
                '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                ('"' + (Join-Path $PSScriptRoot 'darius-manager.ps1') + '"'), '-Action', $selected, '-InteractiveAction')
        })
        $form.Controls.Add($button)
        $description = New-Object Windows.Forms.Label
        $description.UseMnemonic = $false
        $description.Text = $actions[$i][2]
        $description.SetBounds(245, (169 + 42 * $i), 350, 28)
        $form.Controls.Add($description)
    }
    $footer = New-Object Windows.Forms.Label
    $footer.Text = 'ComfyUI and AI model weights stay separate. Optional downloads run only when chosen. No API spending.'
    $footer.SetBounds(28, (170 + 42 * $actions.Count), 555, 36)
    $form.Controls.Add($footer)
    if ($PreviewPath) {
        # Render the real controls for an offline visual check; no actions run.
        $form.Show()
        [Windows.Forms.Application]::DoEvents()
        $bitmap = New-Object Drawing.Bitmap($form.Width, $form.Height)
        try {
            $form.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle(0, 0, $form.Width, $form.Height)))
            $bitmap.Save([IO.Path]::GetFullPath($PreviewPath), [Drawing.Imaging.ImageFormat]::Png)
        } finally { $bitmap.Dispose(); $form.Close() }
    } else { [void]$form.ShowDialog() }
    $form.Dispose()
    exit 0
}

$mutex = $null
$locked = $false
$transcript = $false
$failed = $false
try {
    if ($Action -notin @('Diagnostics', 'Logs', 'Configuration') -and -not $ParentUpdate) {
        $hash = [Security.Cryptography.SHA256]::Create()
        try { $id = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($script:DariusRoot.ToLowerInvariant()))).Replace('-', '') }
        finally { $hash.Dispose() }
        $mutex = New-Object Threading.Mutex($false, "Local\DariusSetup-$id")
        try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
        if (-not $locked) { throw 'Another Darius management action is in progress. Wait for it to finish.' }
    }
    $logs = Join-Path $script:DariusRoot 'data\setup-logs'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    Start-Transcript -Path (Join-Path $logs ((Get-Date -Format 'yyyyMMdd-HHmmss-fff') + "-$Action.log")) | Out-Null
    $transcript = $true
    Write-Host "Darius - $Action"
    switch ($Action) {
        'Install' { Install-DariusCore }
        'BackendRepair' { Repair-DariusBackend }
        'Update' { Update-DariusInstallation }
        'Start' {
            Assert-DariusStopped
            Assert-DariusPortsFree
            if (-not (Test-Path -LiteralPath 'data\installation.json')) { throw 'Run Install / repair first to prepare and build this installation.' }
            Invoke-DariusCommand (Join-Path $script:DariusRoot '.venv\Scripts\python.exe') @('-m', 'alembic', 'upgrade', 'head')
            & (Join-Path $PSScriptRoot 'start-local.ps1') -SkipBuild
            Start-Process 'http://127.0.0.1:3000'
        }
        'Stop' {
            $owned = @(Get-DariusOwnedProcesses)
            # Stop interpreter children before their environment launcher parents.
            $parentIds = @($owned | ForEach-Object ParentProcessId)
            foreach ($process in ($owned | Sort-Object { $parentIds -contains $_.ProcessId })) {
                # Re-read before stopping, protecting against PID reuse.
                $current = @(Get-DariusOwnedProcesses | Where-Object { $_.ProcessId -eq $process.ProcessId -and $_.CreationDate -eq $process.CreationDate })
                if ($current.Count) { Stop-Process -Id $process.ProcessId -ErrorAction Stop }
            }
            Write-Host 'Darius services in this installation stopped. ComfyUI and local model servers were left running.'
        }
        'Diagnostics' { Get-DariusDiagnostics | Format-Table -AutoSize | Out-Host }
        'ConsoleCode' {
            Add-Type -AssemblyName System.Windows.Forms
            $choice = [Windows.Forms.MessageBox]::Show('Open the current console code? Choose Yes to open it. Choose No to reset the code and open its replacement; existing console logins will stop working. Cancel closes.', 'Darius console access', 'YesNoCancel', 'Question')
            if ($choice -ne 'Cancel') {
                $codeArguments = @((Join-Path $PSScriptRoot 'manage-diagnostics.py'))
                if ($choice -eq 'No') { $codeArguments += '--reset' }
                $codePath = & (Join-Path $script:DariusRoot '.venv\Scripts\python.exe') @codeArguments
                if ($LASTEXITCODE -ne 0) { throw 'Could not open the console code. Run Install / repair, or choose No to reset an invalid code file.' }
                Start-Process notepad.exe -ArgumentList ('"' + ($codePath | Select-Object -Last 1).Trim() + '"')
                Write-Host 'Opened the access code for this Darius data folder in Notepad. Paste that code into the console on this server.'
            }
        }
        'Voice' {
            Assert-DariusStopped
            Initialize-DariusUv
            & (Join-Path $PSScriptRoot 'setup-pipecat.ps1')
        }
        'Ollama' {
            Install-DariusOllama
            $choose = [bool]$SelectOllama
            if ($InteractiveAction -and -not $choose) {
                Add-Type -AssemblyName System.Windows.Forms
                $choose = [Windows.Forms.MessageBox]::Show('Ornith 1.5 9B is downloaded and verified. Use it for Darius chat? Yes selects local Ollama and its model; No keeps your current chat provider. Cloud credentials and projects are preserved.',
                    'Local AI ready', 'YesNo', 'Question') -eq 'Yes'
            }
            if ($choose) { Select-DariusOllama }
            else { Write-Host 'Current chat provider retained. To use Ornith later, start Darius, open Settings -> AI model -> Ollama, refresh models and select ornith-1.5:9b.' }
        }
        'Lan' { Assert-DariusStopped; & (Join-Path $PSScriptRoot 'setup-lan-https.ps1') }
        'Configuration' {
            Initialize-DariusConfiguration
            Start-Process notepad.exe -ArgumentList ('"' + (Join-Path $script:DariusRoot '.env') + '"')
            Write-Host 'Set ComfyUI paths and your AI provider here or in Darius Settings. Restart Darius after changing environment settings. Never share this file.'
        }
        'Logs' { Start-Process explorer.exe -ArgumentList ('"' + (Join-Path $script:DariusRoot 'data') + '"') }
    }
    Write-Host 'Done.' -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host 'No automatic retry or reset was attempted. See data\setup-logs for details.'
    $failed = $true
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
    if ($locked) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
if ($InteractiveAction) { [void](Read-Host 'Press Enter to close this progress window') }
if ($failed) { exit 1 }
