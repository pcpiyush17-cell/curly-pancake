$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$log = Join-Path $projectRoot ".mira-launch.log"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Mira's Python environment is missing." -ForegroundColor Yellow
    Write-Host "Open a terminal in $projectRoot and install the desktop dependencies first."
    Read-Host "Press Enter to close"
    exit 1
}

Push-Location $projectRoot
try {
    & $python -m mira.desktop 2> $log
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Mira could not start. Details:" -ForegroundColor Red
        if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log }
        Read-Host "Press Enter to close"
    }
}
finally {
    Pop-Location
}
