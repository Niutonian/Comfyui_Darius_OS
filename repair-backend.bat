@echo off
setlocal
cd /d "%~dp0"
title Darius Backend Repair
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\darius-manager.ps1" -Action BackendRepair -InteractiveAction
