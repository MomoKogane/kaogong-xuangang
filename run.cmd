@echo off
rem xuangang launcher: run run.ps1 with ExecutionPolicy bypass.
setlocal
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PS=pwsh"
where pwsh >nul 2>nul
if errorlevel 1 set "PS=powershell"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
exit /b %errorlevel%
