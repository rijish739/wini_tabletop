@echo off
REM Double-click launcher for the Wini alphabet game (Windows).
REM Uses the repo venv if present, else whatever "python" is on PATH.
setlocal
cd /d "%~dp0"

set PY=python
if exist "..\.venv\Scripts\python.exe" set PY="..\.venv\Scripts\python.exe"

%PY% run_game.py %*
if errorlevel 1 pause
endlocal
