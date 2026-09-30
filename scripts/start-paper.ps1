param([string]$Repository = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Repository).Path
Set-Location -LiteralPath $root
. (Join-Path $PSScriptRoot 'console-helpers.ps1')
Disable-QuickEdit
& (Join-Path $root '.venv\Scripts\forex.exe') run-paper --config (Join-Path $root 'config.yaml')
exit $LASTEXITCODE
