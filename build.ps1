# Build a single-file GrokBar.exe for Windows.
# Usage:  .\build.ps1
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "==> Installing build dependencies..."
python -m pip install -q -r requirements.txt pyinstaller

if ($Clean) {
    Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
    Remove-Item -Force GrokBar.spec -ErrorAction SilentlyContinue
}

$icon = Join-Path $root "assets\icon.ico"
$versionInfo = Join-Path $root "assets\version_info.txt"
if (-not (Test-Path $icon)) {
    Write-Error "Missing icon: $icon"
}

Write-Host "==> Building GrokBar.exe onefile windowed..."
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name GrokBar `
    --icon $icon `
    --version-file $versionInfo `
    --paths $root `
    --hidden-import pystray._win32 `
    --hidden-import PIL._tkinter_finder `
    --collect-all pystray `
    entry.py

$exe = Join-Path $root "dist\GrokBar.exe"
if (-not (Test-Path $exe)) {
    Write-Error "Build failed: $exe not found"
}

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 2)
Write-Host ""
Write-Host "OK  $exe  ${sizeMb}MB"
Write-Host ""
Write-Host "User steps:"
Write-Host "  1. grok login once if needed"
Write-Host "  2. Double-click GrokBar.exe"
Write-Host "  3. Settings gear then Start with Windows optional"
Write-Host "  Note: if SmartScreen warns, More info -> Run anyway (unsigned open-source build)"
