# One-command setup of the paper bot on a fresh Windows VPS (practice money only; no broker orders).
# In PowerShell opened as Administrator:
#   irm https://raw.githubusercontent.com/iamarasinghe96/forex/claude/determined-thompson-f4ewei/scripts/setup-vps.ps1 | iex
# Installs Git and Python 3.12 when missing, downloads the bot to C:\forex, installs its packages,
# runs the tests and creates the "Forex Paper Bot" desktop icon (also started at sign-in).
# Safe to run again: finished steps are skipped and existing files are never deleted.
# It never handles secrets: MT5, .env and the Firebase key file are listed at the end as manual steps.
$ErrorActionPreference = 'Stop'
$Branch = 'claude/determined-thompson-f4ewei'
$Repo = 'https://github.com/iamarasinghe96/forex.git'
$Root = 'C:\forex'
$PythonUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$Python = 'C:\Program Files\Python312\python.exe'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'  # Much faster downloads in Windows PowerShell.
$Temp = Join-Path $env:TEMP 'forex-setup'
New-Item -ItemType Directory -Force -Path $Temp | Out-Null

function Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }
function Check([string]$What) { if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE). Send a screenshot of this window." } }
function Update-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

Step '1/6 Git'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    $release = Invoke-RestMethod 'https://api.github.com/repos/git-for-windows/git/releases/latest' -Headers @{ 'User-Agent' = 'forex-setup' }
    $asset = $release.assets | Where-Object { $_.name -match '^Git-[\d.]+-64-bit\.exe$' } | Select-Object -First 1
    if (-not $asset) { throw 'Could not find the Git for Windows installer. Send a screenshot of this window.' }
    $file = Join-Path $Temp $asset.name
    Write-Host "Downloading $($asset.name)..."
    Invoke-WebRequest $asset.browser_download_url -OutFile $file -UseBasicParsing
    Write-Host 'Installing Git (about a minute)...'
    Start-Process $file -ArgumentList '/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-' -Wait
    Update-Path
}
git --version; Check 'Git'

Step '2/6 Python 3.12'
if (-not (Test-Path $Python)) {
    $file = Join-Path $Temp 'python-3.12.10-amd64.exe'
    Write-Host 'Downloading Python 3.12...'
    Invoke-WebRequest $PythonUrl -OutFile $file -UseBasicParsing
    Write-Host 'Installing Python (a minute or two)...'
    Start-Process $file -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_launcher=1', 'Include_test=0' -Wait
    Update-Path
}
& $Python --version; Check 'Python'

Step '3/6 Bot code in C:\forex'
if (Test-Path (Join-Path $Root '.git')) {
    git -C $Root fetch origin $Branch; Check 'git fetch'
    git -C $Root checkout $Branch; Check 'git checkout'
    git -C $Root pull --ff-only origin $Branch; Check 'git pull'
} else {
    if ((Test-Path $Root) -and @(Get-ChildItem -Force $Root).Count -gt 0) {
        throw 'C:\forex already exists but is not a copy of the bot. Rename that folder (nothing is deleted) and run this again.'
    }
    git clone --branch $Branch $Repo $Root; Check 'git clone'
}
git -C $Root log -1 --format='Code version: %h %s'

Step '4/6 Bot packages (a few minutes)'
$venvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { & $Python -m venv (Join-Path $Root '.venv'); Check 'Creating the Python environment' }
& $venvPython -m pip install --quiet --upgrade pip; Check 'pip upgrade'
& $venvPython -m pip install --quiet -e "$Root[mt5,firebase,dev]"; Check 'Installing the bot packages'
foreach ($folder in 'data', 'logs', '.secrets') { New-Item -ItemType Directory -Force -Path (Join-Path $Root $folder) | Out-Null }

Step '5/6 Tests'
Push-Location $Root
& $venvPython -m pytest -q -p no:cacheprovider | Select-Object -Last 3
$tests = $LASTEXITCODE
Pop-Location
if ($tests -ne 0) { Write-Host 'Some tests failed. Send a screenshot of this window before starting the bot.' -ForegroundColor Yellow }

Step '6/6 Desktop icon'
& (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe') -NoProfile -ExecutionPolicy Bypass `
    -File (Join-Path $Root 'scripts\install-shortcuts.ps1') -Repository $Root; Check 'Creating the icon'

$missing = @()
if (-not (Test-Path (Join-Path $Root '.env'))) { $missing += '.env' }
if (-not (Test-Path (Join-Path $Root '.secrets\firebase-admin.json'))) { $missing += '.secrets\firebase-admin.json' }
$mt5 = @(Get-ChildItem 'C:\Program Files' -Filter terminal64.exe -Recurse -Depth 2 -ErrorAction SilentlyContinue).Count -gt 0
Write-Host "`nSetup finished." -ForegroundColor Green
Write-Host 'Still to do by hand (secrets never go through this script):'
Write-Host ("  [{0}] MetaTrader 5 from IC Markets, logged in to the demo account (server ICMarketsAU-Demo)" -f $(if ($mt5) { 'x' } else { ' ' }))
foreach ($name in '.env', '.secrets\firebase-admin.json') {
    Write-Host ("  [{0}] Copy {1} from the PC (C:\Users\Indika\Desktop\forex\{1}) to C:\forex\{1}" -f $(if ($missing -contains $name) { ' ' } else { 'x' }), $name)
}
Write-Host '  In C:\forex\.env the Firebase line must read: FOREX_FIREBASE_SERVICE_ACCOUNT_FILE=C:/forex/.secrets/firebase-admin.json'
Write-Host 'Then double-click "Forex Paper Bot" on the desktop.'
