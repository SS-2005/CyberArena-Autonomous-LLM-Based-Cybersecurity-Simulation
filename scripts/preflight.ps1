<#
.SYNOPSIS
    CyberArena Phase 1 Preflight Verification Script
.DESCRIPTION
    Checks host environment prerequisites for CyberArena:
    - Python (3.13/3.14) & pip
    - Node.js & npm
    - Git
    - VirtualBox & VBoxManage
    - OpenSSH client
    - Ollama installation status
    - VM registry configuration
    - Network ports (8000, 5173)
#>

$ErrorActionPreference = "Continue"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "         CYBERARENA SYSTEM PREFLIGHT CHECK                " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

$results = @()

function Record-Check {
    param(
        [string]$Component,
        [string]$Status, # PASS, FAIL, WARNING
        [string]$Details
    )
    $script:results += [PSCustomObject]@{
        Component = $Component
        Status    = $Status
        Details   = $Details
    }

    $color = "Green"
    if ($Status -eq "FAIL") { $color = "Red" }
    elseif ($Status -eq "WARNING") { $color = "Yellow" }

    Write-Host ("[{0,-7}] {1,-25} : {2}" -f $Status, $Component, $Details) -ForegroundColor $color
}

# Resolve target Python interpreter (.venv preferred, followed by py -3.13)
$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$targetPython = $null

if (Test-Path $venvPython) {
    $targetPython = $venvPython
    Record-Check "Virtual Environment" "PASS" "Found project .venv ($venvPython)"
} elseif (Get-Command "py" -ErrorAction SilentlyContinue) {
    $pyCheck = py -3.13 --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $targetPython = "py -3.13"
        Record-Check "Virtual Environment" "WARNING" "No .venv found; using system py -3.13"
    }
}

if (-not $targetPython) {
    $targetPython = "python"
}

# 1. Python 3.13 check
try {
    $pyVerRaw = & $targetPython --version 2>&1
    if ($LASTEXITCODE -eq 0 -and $pyVerRaw -match "Python (\d+)\.(\d+)\.?(\d+)?") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -eq 3 -and $minor -eq 13) {
            Record-Check "Python" "PASS" "$pyVerRaw (Standardized Python 3.13 Runtime)"
        } elseif ($major -eq 3 -and $minor -gt 13) {
            Record-Check "Python" "WARNING" "$pyVerRaw (Project standard is Python 3.13; please use .venv with py -3.13)"
        } else {
            Record-Check "Python" "FAIL" "$pyVerRaw (Incompatible version, Python 3.13 required)"
        }
    } else {
        Record-Check "Python" "FAIL" "Target Python not found or failed"
    }
} catch {
    Record-Check "Python" "FAIL" $_.Exception.Message
}

# 2. pip check
try {
    $pipVer = & $targetPython -m pip --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Record-Check "pip" "PASS" $pipVer.Split("from")[0].Trim()
    } else {
        Record-Check "pip" "FAIL" "pip module not found"
    }
} catch {
    Record-Check "pip" "FAIL" $_.Exception.Message
}

# 3. Node.js check
try {
    $nodeVer = node -v 2>&1
    if ($LASTEXITCODE -eq 0) {
        Record-Check "Node.js" "PASS" "$nodeVer"
    } else {
        Record-Check "Node.js" "FAIL" "Node.js not installed or not in PATH"
    }
} catch {
    Record-Check "Node.js" "FAIL" $_.Exception.Message
}

# 4. npm check
try {
    $npmVer = npm -v 2>&1
    if ($LASTEXITCODE -eq 0) {
        Record-Check "npm" "PASS" "v$npmVer"
    } else {
        Record-Check "npm" "FAIL" "npm not found"
    }
} catch {
    Record-Check "npm" "FAIL" $_.Exception.Message
}

# 5. Git check
try {
    $gitVer = git --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Record-Check "Git" "PASS" "$gitVer"
    } else {
        Record-Check "Git" "FAIL" "Git not found"
    }
} catch {
    Record-Check "Git" "FAIL" $_.Exception.Message
}

# 6. VirtualBox & VBoxManage check
$vboxPaths = @(
    "VBoxManage",
    "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
    "C:\Program Files (x86)\Oracle\VirtualBox\VBoxManage.exe"
)
$foundVbox = $null
foreach ($path in $vboxPaths) {
    if (Get-Command $path -ErrorAction SilentlyContinue) {
        $foundVbox = $path
        break
    }
    if (Test-Path $path) {
        $foundVbox = $path
        break
    }
}

if ($foundVbox) {
    try {
        $vboxVer = & $foundVbox --version 2>&1
        Record-Check "VirtualBox" "PASS" "VBoxManage $vboxVer ($foundVbox)"
    } catch {
        Record-Check "VirtualBox" "WARNING" "Found at $foundVbox but failed to query version"
    }
} else {
    Record-Check "VirtualBox" "FAIL" "VBoxManage.exe not found in standard paths or PATH"
}

# 7. SSH Client check
try {
    $sshVer = ssh -V 2>&1
    if ($LASTEXITCODE -eq 0 -or $sshVer -match "OpenSSH") {
        Record-Check "OpenSSH" "PASS" "$sshVer"
    } else {
        Record-Check "OpenSSH" "WARNING" "SSH command did not return OpenSSH identifier"
    }
} catch {
    Record-Check "OpenSSH" "WARNING" "OpenSSH client not found in PATH (Paramiko Python library will be used)"
}

# 8. Ollama check (Not strictly required for Phase 1, but inspected for future phases)
try {
    $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaCmd) {
        $ollamaVer = ollama --version 2>&1
        Record-Check "Ollama" "PASS" "Installed ($ollamaVer) - Ready for Phase 2"
    } else {
        Record-Check "Ollama" "WARNING" "Ollama not in PATH (Required in Phase 2, optional for Phase 1)"
    }
} catch {
    Record-Check "Ollama" "WARNING" "Ollama check encountered error (Optional for Phase 1)"
}

# 9. VM Registry Configuration check
$configPath = Join-Path $PSScriptRoot "..\configs\vms.json"
if (Test-Path $configPath) {
    try {
        $rawConfig = Get-Content $configPath -Raw | ConvertFrom-Json
        $maxVm = $rawConfig.max_vm
        $vmCount = $rawConfig.vms.Count
        if ($maxVm -gt 0) {
            Record-Check "VM Registry" "PASS" "Valid JSON ($configPath): max_vm = $maxVm, configured_vms = $vmCount"
        } else {
            Record-Check "VM Registry" "WARNING" "max_vm is not a positive integer in $configPath"
        }
    } catch {
        Record-Check "VM Registry" "FAIL" "Failed to parse $configPath : $_"
    }
} else {
    Record-Check "VM Registry" "FAIL" "configs/vms.json not found"
}

# 10. Port availability checks
function Check-Port {
    param([int]$Port, [string]$ServiceName)
    try {
        $tcpConn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
        if ($tcpConn) {
            Record-Check "Port $Port ($ServiceName)" "WARNING" "Port $Port is currently in use"
        } else {
            Record-Check "Port $Port ($ServiceName)" "PASS" "Port $Port is free and available"
        }
    } catch {
        Record-Check "Port $Port ($ServiceName)" "PASS" "Port check completed"
    }
}

Check-Port -Port 8000 -ServiceName "FastAPI Backend"
Check-Port -Port 5173 -ServiceName "Vite Frontend"

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "                 PREFLIGHT SUMMARY                        " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$failCount = ($results | Where-Object { $_.Status -eq "FAIL" }).Count
$warnCount = ($results | Where-Object { $_.Status -eq "WARNING" }).Count
$passCount = ($results | Where-Object { $_.Status -eq "PASS" }).Count

Write-Host "Checks Passed  : $passCount" -ForegroundColor Green
Write-Host "Warnings       : $warnCount" -ForegroundColor Yellow
Write-Host "Failures       : $failCount" -ForegroundColor Red
Write-Host ""

if ($failCount -eq 0) {
    Write-Host "PREFLIGHT RESULT: PASS - System environment meets Phase 1 requirements." -ForegroundColor Green
    exit 0
} else {
    Write-Host "PREFLIGHT RESULT: FAIL - Resolve the above failed components." -ForegroundColor Red
    exit 1
}
