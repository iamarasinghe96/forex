param([string]$Repository = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Repository).Path
Set-Location -LiteralPath $root
Write-Output "Read-only Forex VPS check. No settings changed; no credentials printed; no orders sent."
Write-Output "Repository: $root"
Write-Output "PowerShell: $($PSVersionTable.PSVersion)"
Write-Output "UTC: $([DateTimeOffset]::UtcNow.ToString('o'))"
if (Get-Command git -ErrorAction SilentlyContinue) {
    git rev-parse HEAD
    git branch --show-current
    git status --short
} else { Write-Output 'Git: not found' }
$python = Join-Path $root '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $python) {
    & $python --version
    & $python -c 'import importlib.metadata as m; names=["forex-operator","MetaTrader5","firebase-admin","tzdata"]; installed={d.metadata["Name"].lower():d.version for d in m.distributions()}; print({n:installed.get(n.lower(),"MISSING") for n in names})'
} else { Write-Output 'Project virtual environment: missing' }
foreach ($relative in @('.env', 'config.yaml', '.secrets\firebase-admin.json', 'data\paper.sqlite3', 'data\paper-a1000.sqlite3', 'data\HALT_PAPER')) {
    Write-Output "$relative exists: $(Test-Path -LiteralPath (Join-Path $root $relative))"
}
$terminals = @(Get-Process terminal64 -ErrorAction SilentlyContinue)
Write-Output "MT5 terminal process count: $($terminals.Count)"
if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
    Get-ScheduledTask | Where-Object { $_.TaskName -match 'forex|paper-watchdog' } |
        Select-Object TaskName, State | Format-Table -AutoSize
}
Write-Output 'This check does not verify account identity, broker permissions, secrets, recovery or profitability.'
