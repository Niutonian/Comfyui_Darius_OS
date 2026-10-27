[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskSettings = Get-Content -Raw -LiteralPath (Join-Path $taskRoot 'data/lan-https/settings.json') | ConvertFrom-Json
$taskAddress = $taskSettings.address
if ($taskAddress -notmatch '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)' -or -not (Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -eq $taskAddress)) { throw 'The gateway must use an assigned private LAN address.' }
$taskExe = Join-Path $taskRoot 'data/tools/caddy/2.11.7/caddy.exe'
$taskName = 'Darius-LAN-HTTPS-3443'
$taskExisting = Get-NetFirewallRule -Name $taskName -ErrorAction SilentlyContinue
if ($taskExisting) { Write-Host 'The Darius HTTPS firewall rule already exists; it was not widened or replaced.'; return }
New-NetFirewallRule -Name $taskName -DisplayName 'Darius secure LAN voice (TCP 3443, local subnet only)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3443 -LocalAddress $taskAddress -RemoteAddress LocalSubnet -Program $taskExe -Profile Any -EdgeTraversalPolicy Block | Out-Null
Write-Host 'Allowed only the Darius gateway executable on TCP 3443 at the configured LAN IP, from the local subnet. No router or network-profile settings were changed.'
