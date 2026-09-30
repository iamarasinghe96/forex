# One-click launcher: starts the paper bot and restarts it if it stops unexpectedly
# (for example while the market is closed, or after an MT5 disconnect). Ctrl+C stops it.
param([string]$Repository = (Split-Path -Parent $PSScriptRoot), [int]$RetrySeconds = 120)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Repository).Path
Set-Location -LiteralPath $root
. (Join-Path $PSScriptRoot 'console-helpers.ps1')
Disable-QuickEdit
$log = Join-Path $root 'logs\launcher.log'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
function Write-Note([string]$Text) {
    $line = "$([DateTimeOffset]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss')) UTC  $Text"
    Write-Host $line
    Add-Content -LiteralPath $log -Value $line
}
$already = @(Get-CimInstance Win32_Process -Filter "Name='forex.exe'" |
    Where-Object { $_.CommandLine -match 'run-paper' })
if ($already.Count -gt 0) {
    $Host.UI.RawUI.WindowTitle = 'Forex Paper Bot - already running (this window closes itself)'
    Write-Host 'The bot is already running in its own window. This window will close in 10 seconds.' -ForegroundColor Yellow
    Start-Sleep -Seconds 10
    [Environment]::Exit(0)  # Close this window even though the shortcut uses -NoExit.
}
$Host.UI.RawUI.WindowTitle = 'Forex Paper Bot - RUNNING - leave open (minimise is fine)'
Write-Host ''
Write-Host '  FOREX PAPER BOT (practice money only; no broker orders)' -ForegroundColor Green
Write-Host '  Leave this window open. You can minimise it and close Remote Desktop with the X.'
Write-Host '  Do not sign out of Windows. To stop the bot: click this title bar, then press Ctrl+C.'
Write-Host '  Track progress on your phone: dashboard and Telegram.'
Write-Host ''
$bot = Join-Path $root '.venv\Scripts\forex.exe'
while ($true) {
    Write-Note 'Starting the bot.'
    & $bot run-paper --config (Join-Path $root 'config.yaml')
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        Write-Note 'The bot stopped normally. Double-click the desktop icon to start it again.'
        break
    }
    Write-Note "The bot stopped (exit code $code). Trying again in $RetrySeconds seconds; this is normal while the market is closed."
    Start-Sleep -Seconds $RetrySeconds
}
