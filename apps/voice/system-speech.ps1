$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$speechRequest = [Console]::In.ReadToEnd() | ConvertFrom-Json
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voices = @($speaker.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'en-*' })
    if ($speechRequest.action -eq 'voices') {
        $items = @($voices | ForEach-Object { @{ name = $_.VoiceInfo.Name; lang = $_.VoiceInfo.Culture.Name } })
        [Console]::Out.Write((ConvertTo-Json -InputObject $items -Compress))
        exit 0
    }
    if (-not $voices.Count) { throw 'No English Windows speech voice is installed.' }
    $choice = $voices | Where-Object { $_.VoiceInfo.Name -eq $speechRequest.voice } | Select-Object -First 1
    if (-not $choice) { $choice = $voices[0] }
    $speaker.SelectVoice($choice.VoiceInfo.Name)
    $speechBuffer = New-Object IO.MemoryStream
    try {
        $speaker.SetOutputToWaveStream($speechBuffer)
        $speaker.Speak([string]$speechRequest.text)
        $speaker.SetOutputToNull()
        $speechBytes = $speechBuffer.ToArray()
        [Console]::OpenStandardOutput().Write($speechBytes, 0, $speechBytes.Length)
    } finally { $speechBuffer.Dispose() }
} finally { $speaker.Dispose() }
