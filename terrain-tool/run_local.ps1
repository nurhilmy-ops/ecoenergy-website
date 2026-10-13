# One-command local run (Windows). Needs Python 3.11+ from python.org.
# Easiest: double-click START-WINDOWS.bat, which runs this script for you.
# From a PowerShell window (Windows blocks .ps1 files by default), start it with:
#   powershell -ExecutionPolicy Bypass -File .\run_local.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Fail([string]$message) {
    Write-Host ""
    Write-Host "  ERROR: $message" -ForegroundColor Red
    Write-Host ""
    exit 1
}

# Find a Python 3.11+: the "py" launcher (python.org installs) first, then "python".
# The Microsoft Store "python" alias only prints an install hint and exits non-zero, so it is skipped.
function Find-Python {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"     # PowerShell 5.1 would stop on any stderr from a probe
    try {
        foreach ($candidate in @(@("py", "-3"), @("python"), @("python3"))) {
            if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
            $probeArgs = @($candidate | Select-Object -Skip 1)
            $ok = & $candidate[0] @probeArgs -c "import sys; print(int(sys.version_info >= (3, 11)))" 2>$null
            if ($LASTEXITCODE -eq 0 -and "$ok".Trim() -eq "1") { return ,$candidate }
        }
    } finally {
        $ErrorActionPreference = $saved
    }
    return $null
}

# Check for the interpreter, not just the folder: a failed venv run leaves a half-made .venv.
if (-not (Test-Path .venv\Scripts\python.exe)) {
    $python = Find-Python
    if (-not $python) {
        Fail ("Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ " +
              "(on the first installer screen tick 'Add python.exe to PATH'), then run this again.")
    }
    $PyExe = $python[0]
    $PyArgs = @($python | Select-Object -Skip 1)
    Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
    Write-Host "  Setting up (first time only)..."
    & $PyExe @PyArgs -m venv .venv
    if ($LASTEXITCODE) { Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue; exit $LASTEXITCODE }
}

Write-Host "  Installing or checking the required packages. The first run downloads about 150 MB"
Write-Host "  and can take 5-10 minutes - please wait..."
# Windows PowerShell 5.1 does not stop on a failing native command, so check each exit code.
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m pip install --quiet --prefer-binary -r requirements.txt
if ($LASTEXITCODE) { exit $LASTEXITCODE }
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

$port = if ($env:PORT) { $env:PORT } else { "8000" }
Write-Host ""
Write-Host "  Terrain screening tool  ->  http://localhost:$port"
Write-Host "  Dev inbox (magic links) ->  http://localhost:$port/dev/outbox"
Write-Host "  Admin (leads)           ->  http://localhost:$port/admin   (user/password from .env)"
Write-Host ""
Write-Host "  Leave this window open while you use the tool. Close it (or press Ctrl+C) to stop."
Write-Host ""
& .\.venv\Scripts\python.exe -m app
