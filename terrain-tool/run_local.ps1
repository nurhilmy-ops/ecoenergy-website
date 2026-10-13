# One-command local run (Windows PowerShell). Needs Python 3.11+ ("py" launcher).
# Windows blocks scripts by default, so start it with:
#   powershell -ExecutionPolicy Bypass -File .\run_local.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Check for the interpreter, not just the folder: a failed venv run leaves a half-made .venv.
if (-not (Test-Path .venv\Scripts\python.exe)) {
    Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
    py -3 -m venv .venv
    if ($LASTEXITCODE) { Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue; exit $LASTEXITCODE }
}
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
& .\.venv\Scripts\python.exe -m app
