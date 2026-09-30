# Creates a "Forex Paper Bot" icon on the desktop and, unless -NoStartup is given, in the
# Windows Startup folder so the bot also starts when this user signs in (e.g. after a reboot).
param([string]$Repository = (Split-Path -Parent $PSScriptRoot), [switch]$NoStartup)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Repository).Path
$powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = "-NoExit -NoProfile -ExecutionPolicy Bypass -File `"$root\scripts\run-bot.ps1`" -Repository `"$root`""
$shell = New-Object -ComObject WScript.Shell
$places = @(@{Folder = [Environment]::GetFolderPath('Desktop'); Window = 1})
if (-not $NoStartup) { $places += @{Folder = [Environment]::GetFolderPath('Startup'); Window = 7} }
foreach ($place in $places) {
    $path = Join-Path $place.Folder 'Forex Paper Bot.lnk'
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $powershell
    $link.Arguments = $arguments
    $link.WorkingDirectory = $root
    $link.WindowStyle = $place.Window
    $link.IconLocation = "$env:WINDIR\System32\shell32.dll,43"
    $link.Description = 'Start the Forex paper bot (practice money only)'
    $link.Save()
    Write-Output "Created: $path"
}
