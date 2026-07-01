<#
.SYNOPSIS
    Add a "BTX Windows Miner" shortcut to your Desktop that launches the GUI.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install-desktop-shortcut.ps1
#>
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot

$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
if (-not $py) {
    Write-Error "Python not found on PATH. Install Python 3.10+ from https://www.python.org/downloads/ (tick 'Add to PATH')."
    exit 1
}

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop "BTX Windows Miner.lnk"
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath = $py
$lnk.Arguments = "`"$repo\gui\btx_miner_gui.py`""
$lnk.WorkingDirectory = $repo
if (Test-Path "$repo\gui\btx.ico") { $lnk.IconLocation = "$repo\gui\btx.ico" }
$lnk.Description = "BTX native Windows CUDA miner"
$lnk.Save()

Write-Host "Desktop shortcut created: $lnkPath" -ForegroundColor Green
