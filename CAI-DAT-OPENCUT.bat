@echo off
setlocal
cd /d "%~dp0"
title Cai dat OpenCut SAM 2.1

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\install-opencut.ps1"
set "INSTALL_RESULT=%ERRORLEVEL%"

echo.
if not "%INSTALL_RESULT%"=="0" (
  echo Cai dat chua hoan tat. Hay xem thong bao loi phia tren.
  pause
  exit /b %INSTALL_RESULT%
)

echo Cai dat thanh cong. OpenCut se duoc khoi dong ngay bay gio.
pause
call "%~dp0MO-OPENCUT.bat"

