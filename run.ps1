# Launch GrokBar in the system tray.
param(
    [switch]$Background,
    [int]$Refresh = 120,
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found. Install Python 3.10+ and try again."
}

& python -m pip install -r requirements.txt -q

$moduleArgs = @("-m", "grok_bar", "--refresh", "$Refresh")
if ($Once) {
    $moduleArgs += "--once"
    & python @moduleArgs
    exit $LASTEXITCODE
}

if ($Background) {
    $pythonw = Get-Command pythonw -ErrorAction SilentlyContinue
    if (-not $pythonw) {
        Write-Error "pythonw not found. Install Python with pythonw.exe or run without -Background."
    }
    Start-Process -FilePath $pythonw.Source -ArgumentList $moduleArgs -WorkingDirectory $root -WindowStyle Hidden
    Write-Host "GrokBar started in the system tray."
} else {
    & python @moduleArgs
}
