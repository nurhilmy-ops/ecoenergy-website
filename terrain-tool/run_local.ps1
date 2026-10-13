# One-command local run (Windows PowerShell). Needs Python 3.11+ ("py" launcher).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { py -3 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

$port = if ($env:PORT) { $env:PORT } else { "8000" }
Write-Host ""
Write-Host "  Terrain screening tool  ->  http://localhost:$port"
Write-Host "  Dev inbox (magic links) ->  http://localhost:$port/dev/outbox"
Write-Host "  Admin (leads)           ->  http://localhost:$port/admin   (user/password from .env)"
Write-Host ""
& .\.venv\Scripts\python.exe -m app
