@echo off
setlocal
cd /d "%~dp0"
echo EXPERIMENTAL sandbox execution prototype. Docker is required; external writes stay disabled.
call "%~dp0runtime.cmd"
if errorlevel 1 exit /b %errorlevel%
"%SWARM_PYTHON%" swarm.py start --project "%~dp0..\.." --runs-root "%SWARM_RUNS_ROOT%" --config "%~dp0config.http.json" --backend openai --mode autonomous --experiments docker --external-scope sandbox-only --approval required --fetch-live %*
exit /b %errorlevel%
