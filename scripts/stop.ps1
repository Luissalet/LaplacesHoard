# Stops Laplace's Hoard (and its computation worker process).
#
# Only stops a process that answers /api/health as "laplaces-hoard", so
# another program that happens to use the same port is never killed.
# Usage: scripts\stop.ps1 [-Port 8812]
# Compatible with Windows PowerShell 5.1 and PowerShell 7.
param([int]$Port = 8812)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$OnWindows = ($env:OS -eq "Windows_NT")
$AppUrl = "http://127.0.0.1:$Port"
$PidFile = Join-Path $RepoRoot "data\laplace.pid"

function Test-Laplace {
    try {
        $health = Invoke-RestMethod -Uri "$AppUrl/api/health" -TimeoutSec 2 -UseBasicParsing
        return ($health.service -eq "laplaces-hoard")
    } catch {
        return $false
    }
}

function Stop-Tree([int]$ProcessId) {
    if ($OnWindows) {
        # /T also ends the worker process the app started
        & taskkill.exe /PID $ProcessId /T /F | Out-Null
    } else {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Laplace)) {
    Write-Host "Laplace's Hoard is not running on port $Port."
    if (Test-Path -LiteralPath $PidFile) { Remove-Item -LiteralPath $PidFile -Force }
    exit 0
}

$Targets = @()
if ($OnWindows) {
    try {
        $Targets = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        $Targets = @()
    }
}
if ($Targets.Count -eq 0 -and (Test-Path -LiteralPath $PidFile)) {
    $Targets = @([int](Get-Content -LiteralPath $PidFile -Raw).Trim())
}
if ($Targets.Count -eq 0) {
    Write-Host "Laplace's Hoard answers on $AppUrl but its process was not found; close it from the window that started it."
    exit 1
}

foreach ($target in $Targets) {
    Write-Host "Stopping Laplace's Hoard (process $target)..."
    Stop-Tree $target
}

$Deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $Deadline -and (Test-Laplace)) { Start-Sleep -Milliseconds 300 }
if (Test-Path -LiteralPath $PidFile) { Remove-Item -LiteralPath $PidFile -Force }
if (Test-Laplace) {
    Write-Host "Laplace's Hoard is still answering on $AppUrl."
    exit 1
}
Write-Host "Stopped."
