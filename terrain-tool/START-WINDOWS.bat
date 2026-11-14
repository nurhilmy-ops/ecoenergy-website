@echo off
rem Double-click this file to start the EcoEnergy terrain screening tool on this computer.
rem It installs what it needs the first time (5-10 minutes), then opens your web browser.
title EcoEnergy terrain screening tool
cd /d "%~dp0"
set OPEN_BROWSER=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_local.ps1"
if errorlevel 1 (
  echo.
  echo   The tool stopped with an error. Read the message above, then press any key to close.
  pause > nul
)
