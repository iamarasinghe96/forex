param(
    [string]$Repository = (Split-Path -Parent $PSScriptRoot),
    [int]$MaximumHeartbeatAgeSeconds = 120
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Repository).Path
$heartbeat = Join-Path $root 'data\paper-heartbeat.json'
$halt = Join-Path $root 'data\HALT_PAPER'
try {
    $record = Get-Content -Raw -LiteralPath $heartbeat | ConvertFrom-Json
    $age = ([DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse($record.observed_at_utc)).TotalSeconds
    if ($record.mode -ne 'PAPER' -or $age -lt 0 -or $age -gt $MaximumHeartbeatAgeSeconds) { throw 'Stale heartbeat' }
    Write-Output 'Paper heartbeat is recent; this is not strategy or broker validation.'
} catch {
    # Fail closed. Never kill MT5 or automatically restart an uncertain trading process.
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $halt) | Out-Null
    Set-Content -LiteralPath $halt -Value 'Watchdog detected missing/invalid/stale paper heartbeat. Review before removing this latch.'
    Write-Error 'Paper heartbeat failed. Halt latch written; inspect the runtime and retained positions.'
    exit 2
}
