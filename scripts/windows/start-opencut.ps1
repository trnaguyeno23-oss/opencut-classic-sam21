$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$SamLauncher = Join-Path $ProjectRoot "services\sam21\start-windows.ps1"
$WebLauncher = Join-Path $PSScriptRoot "start-web.ps1"
$SamPython = Join-Path $ProjectRoot "services\sam21\.venv\Scripts\python.exe"

if (-not (Test-Path $SamPython)) {
    throw "OpenCut chua duoc cai dat. Hay chay CAI-DAT-OPENCUT.bat truoc."
}

if (-not (Get-Command bun.exe -ErrorAction SilentlyContinue)) {
    $MachinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $KnownPaths = @(
        (Join-Path $env:USERPROFILE ".bun\bin"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links")
    ) -join ";"
    $env:Path = "$MachinePath;$UserPath;$KnownPaths"
}

if (-not (Get-Command bun.exe -ErrorAction SilentlyContinue)) {
    throw "Khong tim thay Bun. Hay khoi dong lai may hoac chay lai bo cai."
}

function Test-LocalUrl {
    param([string]$Url)
    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

if (-not (Test-LocalUrl "http://127.0.0.1:8788/health")) {
    Write-Host "Dang mo SAM 2.1..." -ForegroundColor Cyan
    Start-Process powershell.exe -ArgumentList @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$SamLauncher`""
    )
}
else {
    Write-Host "SAM 2.1 dang chay." -ForegroundColor Green
}

if (-not (Test-LocalUrl "http://127.0.0.1:3000")) {
    Write-Host "Dang mo OpenCut..." -ForegroundColor Cyan
    Start-Process powershell.exe -ArgumentList @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$WebLauncher`""
    )
}
else {
    Write-Host "OpenCut dang chay." -ForegroundColor Green
}

Write-Host "Dang cho OpenCut san sang..."
$Ready = $false
for ($Attempt = 0; $Attempt -lt 90; $Attempt++) {
    if (Test-LocalUrl "http://127.0.0.1:3000") {
        $Ready = $true
        break
    }
    Start-Sleep -Seconds 1
}

if (-not $Ready) {
    throw "OpenCut chua khoi dong sau 90 giay. Hay xem loi trong cua so OpenCut vua mo."
}

Start-Process "http://127.0.0.1:3000"
Write-Host "Da mo OpenCut trong trinh duyet." -ForegroundColor Green
