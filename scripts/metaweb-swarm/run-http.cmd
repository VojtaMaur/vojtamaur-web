@echo off
echo run-http now starts brainstorming. For experimental execution use run-experimental.cmd.
call "%~dp0run.cmd" %*
exit /b %errorlevel%
