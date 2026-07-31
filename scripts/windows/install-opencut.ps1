$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$SamSetup = Join-Path $ProjectRoot "services\sam21\setup-windows.ps1"
$EnvExample = Join-Path $ProjectRoot "apps\web\.env.example"
$EnvLocal = Join-Path $ProjectRoot "apps\web\.env.local"

function Refresh-ProcessPath {
    $MachinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $KnownPaths = @(
        (Join-Path $env:USERPROFILE ".bun\bin"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\Scripts")
    ) -join ";"
    $env:Path = "$MachinePath;$UserPath;$KnownPaths"
}

function Install-WithWinget {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw "Khong tim thay winget. Hay cap nhat App Installer trong Microsoft Store roi chay lai."
    }

    Write-Host "Dang cai $Name..." -ForegroundColor Cyan
    & winget.exe install --exact --id $Id --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        throw "Khong cai duoc $Name (winget exit code $LASTEXITCODE)."
    }
    Refresh-ProcessPath
}

function Add-ToUserPath {
    param([Parameter(Mandatory = $true)][string]$Directory)
    $Current = [Environment]::GetEnvironmentVariable("Path", "User")
    $Parts = @($Current -split ";" | Where-Object { $_ })
    if ($Parts -notcontains $Directory) {
        $NewPath = (@($Parts) + $Directory) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    }
    if (($env:Path -split ";") -notcontains $Directory) {
        $env:Path += ";$Directory"
    }
}

Write-Host "=== CAI DAT OPENCUT + SAM 2.1 CPU ===" -ForegroundColor Green
Write-Host "Thu muc: $ProjectRoot"
Refresh-ProcessPath

$Python311Ready = $false
$ExistingPython = Get-Command python.exe -ErrorAction SilentlyContinue
if ($ExistingPython) {
    & $ExistingPython.Source -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
    $Python311Ready = ($LASTEXITCODE -eq 0)
}
if (-not $Python311Ready) {
    Install-WithWinget -Id "Python.Python.3.11" -Name "Python 3.11"
}

if (-not (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue)) {
    Install-WithWinget -Id "Gyan.FFmpeg" -Name "FFmpeg"
}

if (-not (Get-Command bun.exe -ErrorAction SilentlyContinue)) {
    Install-WithWinget -Id "Oven-sh.Bun" -Name "Bun"
}

# Some WinGet packages update PATH only after a new terminal is opened.
# Create process-local paths immediately so this one-click run can continue.
$WingetPackages = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
$FfmpegPackage = Get-ChildItem $WingetPackages -Directory -Filter "Gyan.FFmpeg_*" `
    -ErrorAction SilentlyContinue | Select-Object -First 1
$FfmpegFromWinget = if ($FfmpegPackage) {
    Get-ChildItem $FfmpegPackage.FullName -Filter "ffmpeg.exe" -File -Recurse `
        -ErrorAction SilentlyContinue | Select-Object -First 1
}
if ($FfmpegFromWinget) {
    Add-ToUserPath $FfmpegFromWinget.DirectoryName
}
$BunPackage = Get-ChildItem $WingetPackages -Directory -Filter "Oven-sh.Bun_*" `
    -ErrorAction SilentlyContinue | Select-Object -First 1
$BunFromWinget = if ($BunPackage) {
    Get-ChildItem $BunPackage.FullName -Filter "bun.exe" -File -Recurse `
        -ErrorAction SilentlyContinue | Select-Object -First 1
}
if ($BunFromWinget) {
    Add-ToUserPath $BunFromWinget.DirectoryName
}

foreach ($Command in @("python.exe", "ffmpeg.exe", "bun.exe")) {
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "Da cai nhung Windows chua nhan dien $Command. Hay khoi dong lai may va chay lai file CAI-DAT-OPENCUT.bat."
    }
}

$Python311 = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
$PythonPath = if (Test-Path $Python311) {
    $Python311
}
else {
    (Get-Command python.exe).Source
}
$env:SAM21_PYTHON = $PythonPath

if (-not (Test-Path $EnvLocal)) {
    Copy-Item $EnvExample $EnvLocal
    Write-Host "Da tao cau hinh OpenCut." -ForegroundColor Green
}

Write-Host "Dang cai thu vien OpenCut..." -ForegroundColor Cyan
Push-Location $ProjectRoot
try {
    & bun.exe install
    if ($LASTEXITCODE -ne 0) {
        throw "bun install that bai (exit code $LASTEXITCODE)."
    }
}
finally {
    Pop-Location
}

Write-Host "Dang cai SAM 2.1 Tiny ban CPU. Buoc nay co the mat nhieu phut..." -ForegroundColor Cyan
& $SamSetup
if ($LASTEXITCODE -ne 0) {
    throw "Cai SAM 2.1 that bai (exit code $LASTEXITCODE)."
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "OpenCut SAM 2.1.lnk"
$LauncherPath = Join-Path $ProjectRoot "MO-OPENCUT.bat"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $LauncherPath
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "Mo OpenCut va dich vu SAM 2.1 local"
$Shortcut.Save()

Write-Host "" 
Write-Host "CAI DAT HOAN TAT" -ForegroundColor Green
Write-Host "Da tao bieu tuong 'OpenCut SAM 2.1' ngoai Desktop."
