# Starts Laplace's Hoard from the repo root (so faustus-plugin.json is found
# in the process working directory). Creates the venv and installs the
# lock file on first run.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

$MarkerFile = ".venv\.deps-installed"
if (-not (Test-Path $MarkerFile)) {
    Write-Host "Installing dependencies..."
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r requirements-lock.txt
    New-Item -ItemType File -Path $MarkerFile | Out-Null
}

if ((Test-Path "frontend\package.json") -and (-not (Test-Path "frontend\dist\index.html"))) {
    Write-Host "Building frontend..."
    Push-Location frontend
    npm ci
    npm run build
    Pop-Location
}

Write-Host "Starting Laplace's Hoard on http://127.0.0.1:8812 ..."
& $Python -m laplaces_hoard --port 8812
