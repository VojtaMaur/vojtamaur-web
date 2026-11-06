@echo off
setlocal
cd /d "%~dp0"
call "%~dp0runtime.cmd"
if errorlevel 1 exit /b %errorlevel%
"%SWARM_PYTHON%" swarm.py gui --project "%~dp0..\.." --runs-root "%SWARM_RUNS_ROOT%" %*
exit /b %errorlevel%
