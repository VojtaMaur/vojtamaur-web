@echo off
setlocal
cd /d "%~dp0"
if not defined SWARM_PYTHON (
  if exist "%~dp0.venv\Scripts\python.exe" (
    set "SWARM_PYTHON=%~dp0.venv\Scripts\python.exe"
  ) else if exist "G:\metaweb-swarm-env\Scripts\python.exe" (
    set "SWARM_PYTHON=G:\metaweb-swarm-env\Scripts\python.exe"
  ) else (
    set "SWARM_PYTHON=python"
  )
)
if not defined SWARM_RUNS_ROOT set "SWARM_RUNS_ROOT=%~dp0..\..\..\metaweb-swarm-runs"
"%SWARM_PYTHON%" swarm.py start --project "%~dp0..\.." --runs-root "%SWARM_RUNS_ROOT%" --config "%~dp0config.research.json" --backend openai --mode autonomous --experiments docker --external-scope sandbox-only --approval required --fetch-live %*
exit /b %errorlevel%
