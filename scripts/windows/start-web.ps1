$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

$MachinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$KnownPaths = @(
    (Join-Path $env:USERPROFILE ".bun\bin"),
    (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links")
) -join ";"
$env:Path = "$MachinePath;$UserPath;$KnownPaths"

Set-Location $ProjectRoot
& bun.exe dev:web
