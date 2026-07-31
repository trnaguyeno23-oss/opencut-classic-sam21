$ErrorActionPreference = "Stop"
$ServiceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ServiceRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Chua cai dat. Hay chay .\setup-windows.ps1 truoc."
}

Set-Location $ServiceRoot
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8788
