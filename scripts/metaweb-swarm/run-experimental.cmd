@echo off
setlocal
cd /d "%~dp0"
echo EXPERIMENTAL autonomous execution prototype. Docker and external approvals are required.
call "%~dp0runtime.cmd"
if errorlevel 1 exit /b %errorlevel%
"%SWARM_PYTHON%" swarm.py start --project "%~dp0..\.." --runs-root "%SWARM_RUNS_ROOT%" --config "%~dp0config.http.json" --backend openai --mode autonomous --experiments docker --external-scope external --approval required --fetch-live %*
exit /b %errorlevel%
