@echo off
setlocal
cd /d "%~dp0"
call "%~dp0runtime.cmd"
if errorlevel 1 exit /b %errorlevel%
"%SWARM_PYTHON%" swarm.py start --project "%~dp0..\.." --runs-root "%SWARM_RUNS_ROOT%" --config "%~dp0config.http-public-smoke.json" --backend openai --mode autonomous --experiments disabled --external-scope external --approval disabled --no-fetch-live %*
exit /b %errorlevel%
