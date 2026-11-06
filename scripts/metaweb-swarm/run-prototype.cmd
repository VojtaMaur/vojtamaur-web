@echo off
setlocal
cd /d "%~dp0"
call "%~dp0runtime.cmd"
if errorlevel 1 exit /b %errorlevel%
"%SWARM_PYTHON%" swarm.py start --project "%~dp0..\.." --runs-root "%SWARM_RUNS_ROOT%" --config "%~dp0config.prototype.json" --backend openai --mode autonomous --experiments docker --external-scope sandbox-only --approval required %*
exit /b %errorlevel%
