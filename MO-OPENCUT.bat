@echo off
setlocal
cd /d "%~dp0"
title Khoi dong OpenCut SAM 2.1

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\start-opencut.ps1"
if errorlevel 1 (
  echo.
  echo Khong the khoi dong OpenCut. Hay xem thong bao loi phia tren.
  pause
)

