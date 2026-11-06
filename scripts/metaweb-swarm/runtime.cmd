@echo off
rem Shared runtime layout. Caller owns SETLOCAL so these variables stay local.
if not defined SWARM_FILES_ROOT for %%I in ("%~dp0..\..\..\vojtamaur-metaweb-swarm-files") do set "SWARM_FILES_ROOT=%%~fI"
if not defined SWARM_PYTHON (
  if exist "%~dp0.venv\Scripts\python.exe" (
    set "SWARM_PYTHON=%~dp0.venv\Scripts\python.exe"
  ) else if exist "%SWARM_FILES_ROOT%\env\Scripts\python.exe" (
    set "SWARM_PYTHON=%SWARM_FILES_ROOT%\env\Scripts\python.exe"
  ) else (
    set "SWARM_PYTHON=python"
  )
)
if not defined SWARM_RUNS_ROOT set "SWARM_RUNS_ROOT=%SWARM_FILES_ROOT%\runs"
exit /b 0
