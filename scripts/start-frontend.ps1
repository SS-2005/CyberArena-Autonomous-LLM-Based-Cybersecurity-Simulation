<#
.SYNOPSIS
    Starts CyberArena Vite Frontend Dev Server
#>
Write-Host "Starting CyberArena Frontend on http://127.0.0.1:5173 ..." -ForegroundColor Cyan
Set-Location "$PSScriptRoot\..\frontend"
npm run dev
