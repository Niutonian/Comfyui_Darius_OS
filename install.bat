@echo off
setlocal
cd /d "%~dp0"
title Darius Setup
powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0scripts\darius-manager.ps1" %*
if errorlevel 1 pause
