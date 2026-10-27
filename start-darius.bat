@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Darius AI Launcher

set "PYTHON=%CD%\.venv\Scripts\python.exe"
set "WEB_MODULES=%CD%\apps\web\node_modules"
set "START_SCRIPT=%CD%\scripts\start-local.ps1"

if not exist "%PYTHON%" goto :missing_python
if not exist "%WEB_MODULES%" goto :missing_web
if not exist "%START_SCRIPT%" goto :missing_script

if /I "%~1"=="check" goto :check
if /I "%~1"=="worker" goto :start_worker
if not "%~1"=="" goto :usage

set "WORKER_ARG="
goto :start

:start_worker
set "WORKER_ARG=-WithWorker"
echo WARNING: The generation worker will execute explicitly approved queued jobs.
echo          Local GPU workflows can take many minutes.
echo.

:start
echo ============================================================
echo  Darius AI
if defined WORKER_ARG (echo  Mode: API + Web + Generation Worker) else (echo  Mode: API + Web ^(render workers start on demand^))
echo ============================================================
echo.
echo Applying database migrations...
"%PYTHON%" -m alembic upgrade head
if errorlevel 1 goto :migration_failed

echo.
echo Starting Darius...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%START_SCRIPT%" %WORKER_ARG%
if errorlevel 1 goto :startup_failed

echo.
echo Waiting for the local web server, then opening Darius...
timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:3000"

echo.
echo Darius is starting in the background:
echo   Web:     http://127.0.0.1:3000
echo   API:     http://127.0.0.1:8000
echo   API docs:http://127.0.0.1:8000/docs
echo.
echo You may close this window; the started processes will continue running.
pause
exit /b 0

:check
echo Checking Darius launcher prerequisites...
"%PYTHON%" -c "import alembic, fastapi, sqlalchemy, darius_api; print('Python backend: OK')"
if errorlevel 1 goto :check_failed
where npm.cmd >nul 2>nul
if errorlevel 1 goto :missing_npm
call npm.cmd --version >nul
if errorlevel 1 goto :missing_npm
echo Frontend dependencies: OK
echo PowerShell startup script: OK
echo Darius launcher check: PASSED
exit /b 0

:missing_python
echo ERROR: Python environment not found:
echo   %PYTHON%
echo Run the setup commands in README.md first.
goto :failed

:missing_web
echo ERROR: Frontend dependencies are missing:
echo   %WEB_MODULES%
echo Run: cd apps\web ^&^& npm ci
goto :failed

:missing_script
echo ERROR: Startup script not found:
echo   %START_SCRIPT%
goto :failed

:missing_npm
echo ERROR: npm.cmd was not found. Install Node.js and npm.
goto :failed

:migration_failed
echo ERROR: Database migration failed. Review the messages above.
goto :failed

:startup_failed
echo ERROR: Darius could not start. Review the messages above.
goto :failed

:check_failed
echo ERROR: Backend dependency check failed.
goto :failed

:usage
echo Usage:
echo   start-darius.bat          Start API and web without generation worker
echo   start-darius.bat worker   Start API, web, and generation worker
echo   start-darius.bat check    Validate prerequisites without starting
exit /b 2

:failed
pause
exit /b 1
