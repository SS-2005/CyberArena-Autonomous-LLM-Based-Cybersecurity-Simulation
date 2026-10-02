<#
.SYNOPSIS
    Starts CyberArena FastAPI Backend Server using standardized Python 3.13 virtual environment.
#>
$ErrorActionPreference = "Stop"

$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$venvActivate = Join-Path $PSScriptRoot "..\.venv\Scripts\Activate.ps1"

if (Test-Path $venvPython) {
    if (Test-Path $venvActivate) {
        Write-Host "Activating project virtual environment (.venv)..." -ForegroundColor Cyan
        & $venvActivate
    }
    $pyCmd = $venvPython
} else {
    Write-Host "Warning: .venv not found. Falling back to system py -3.13 launcher..." -ForegroundColor Yellow
    $pyCmd = "py -3.13"
}

$pyVer = & $venvPython --version 2>&1
Write-Host "Runtime: $pyVer" -ForegroundColor Green
Write-Host "Starting CyberArena Backend API on http://127.0.0.1:8000 ..." -ForegroundColor Cyan

& $venvPython -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
