# Starts Laplace's Hoard and waits until it answers on /api/health.
#
# - runs from the repo root, so faustus-plugin.json is in the process
#   working directory (Faustus reads it from there);
# - first run: creates .venv, installs requirements-lock.txt (again whenever
#   the lock file changes) and builds the frontend if frontend/dist is missing;
# - starts the app hidden in the background (log: data/logs/server.log),
#   waits for /api/health, then opens the browser.
#
# Usage: scripts\start.ps1 [-Port 8812] [-Demo] [-NoBrowser]
# Compatible with Windows PowerShell 5.1 and PowerShell 7.
param(
    [int]$Port = 8812,
    [switch]$Demo,
    [switch]$NoBrowser,
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot
$OnWindows = ($env:OS -eq "Windows_NT")
$AppUrl = "http://127.0.0.1:$Port"

function Test-Laplace {
    try {
        $health = Invoke-RestMethod -Uri "$AppUrl/api/health" -TimeoutSec 2 -UseBasicParsing
        return ($health.service -eq "laplaces-hoard")
    } catch {
        return $false
    }
}

function Invoke-Checked([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed (exit code $LASTEXITCODE)."
    }
}

function Find-BasePython {
    # Prefer the Python the app is built for (3.13), then any Python 3.11+.
    $candidates = @()
    if ($OnWindows) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            foreach ($v in @("3.13", "3.12", "3.11")) { $candidates += ,@("py", "-$v") }
        }
        foreach ($p in @("C:\Python313\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe")) {
            if (Test-Path -LiteralPath $p) { $candidates += ,@($p) }
        }
    }
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += ,@($cmd.Source) }
    }
    foreach ($c in $candidates) {
        $exe = $c[0]
        $extra = @()
        if ($c.Count -gt 1) { $extra = $c[1..($c.Count - 1)] }
        try {
            $ok = & $exe @extra -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
            if ($LASTEXITCODE -eq 0 -and "$ok".Trim() -eq "True") { return ,$c }
        } catch { }
    }
    throw "Python 3.11 or newer was not found. Install Python 3.13 (python.org) and run this again."
}

if (Test-Laplace) {
    Write-Host "Laplace's Hoard is already running at $AppUrl"
    if (-not $NoBrowser) { Start-Process $AppUrl }
    exit 0
}

# --- Python environment -------------------------------------------------------
if ($OnWindows) { $Python = Join-Path $RepoRoot ".venv\Scripts\python.exe" }
else { $Python = Join-Path $RepoRoot ".venv/bin/python" }

if (-not (Test-Path -LiteralPath $Python)) {
    $base = Find-BasePython
    $exe = $base[0]
    $extra = @()
    if ($base.Count -gt 1) { $extra = $base[1..($base.Count - 1)] }
    Write-Host "Creating the virtual environment (.venv)..."
    Invoke-Checked "Creating .venv" { & $exe @extra -m venv .venv }
}

$LockFile = Join-Path $RepoRoot "requirements-lock.txt"
$Marker = Join-Path $RepoRoot ".venv\.lock-installed"
$LockHash = (Get-FileHash -LiteralPath $LockFile -Algorithm SHA256).Hash
$Installed = ""
if (Test-Path -LiteralPath $Marker) { $Installed = (Get-Content -LiteralPath $Marker -Raw).Trim() }
if ($Installed -ne $LockHash) {
    Write-Host "Installing dependencies from requirements-lock.txt (first run takes a few minutes)..."
    Invoke-Checked "Upgrading pip" { & $Python -m pip install --disable-pip-version-check --upgrade pip }
    Invoke-Checked "Installing dependencies" { & $Python -m pip install --disable-pip-version-check -r $LockFile }
    Set-Content -LiteralPath $Marker -Value $LockHash -Encoding ascii
}

# --- Frontend -----------------------------------------------------------------
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "frontend\dist\index.html"))) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "Building the interface (frontend/dist)..."
        Push-Location -LiteralPath (Join-Path $RepoRoot "frontend")
        try {
            Invoke-Checked "npm ci" { npm ci --no-audit --no-fund }
            Invoke-Checked "npm run build" { npm run build }
        } finally {
            Pop-Location
        }
    } else {
        Write-Warning "Node.js/npm not found: the API will run, but the web interface needs 'npm ci; npm run build' in frontend/."
    }
}

# --- Start and wait for /api/health -------------------------------------------
$LogDir = Join-Path $RepoRoot "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$OutLog = Join-Path $LogDir "server.log"
$ErrLog = Join-Path $LogDir "server.err.log"

$AppArgs = @("-m", "laplaces_hoard", "--port", "$Port", "--no-browser")
if ($Demo) { $AppArgs += "--demo" }

Write-Host "Starting Laplace's Hoard on $AppUrl ..."
$StartParams = @{
    FilePath               = $Python
    ArgumentList           = $AppArgs
    WorkingDirectory       = $RepoRoot
    RedirectStandardOutput = $OutLog
    RedirectStandardError  = $ErrLog
    PassThru               = $true
}
if ($OnWindows) { $StartParams["WindowStyle"] = "Hidden" }
$Proc = Start-Process @StartParams
Set-Content -LiteralPath (Join-Path $RepoRoot "data\laplace.pid") -Value $Proc.Id -Encoding ascii

$Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $Deadline) {
    if (Test-Laplace) {
        Write-Host "Laplace's Hoard is running at $AppUrl (process $($Proc.Id))."
        Write-Host "Stop it with 'Detener Laplace's Hoard.cmd' or scripts\stop.ps1."
        if (-not $NoBrowser) { Start-Process $AppUrl }
        exit 0
    }
    if ($Proc.HasExited) {
        Write-Host "The app exited during start-up (exit code $($Proc.ExitCode)). Last lines of the log:"
        if (Test-Path -LiteralPath $ErrLog) { Get-Content -LiteralPath $ErrLog -Tail 20 }
        exit 1
    }
    Start-Sleep -Milliseconds 500
}
Write-Host "The app did not answer on $AppUrl/api/health within $TimeoutSeconds s. See $ErrLog"
exit 1
