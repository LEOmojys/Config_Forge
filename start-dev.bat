@echo off
setlocal

set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%start-dev.ps1" %*

if errorlevel 1 (
  echo.
  echo ConfigForge startup failed. See the error above.
  pause
)
