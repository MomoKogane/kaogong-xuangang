@echo off
cd /d "%~dp0"
title Kaogong Xuangang
echo ============================================
echo   Kaogong Xuangang
echo   The browser will open automatically.
echo   Close this window to stop the server.
echo ============================================
call run.cmd serve
pause
