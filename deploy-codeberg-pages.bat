@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem ------------------------------------------------------------
rem Deploy the current Astro build to Codeberg Pages.
rem Expected layout next to this script:
rem   deploy-codeberg-pages.bat
rem   vojtamaur-web\   (branch main)
rem   vojtamaur-pages\ (branch pages)
rem This script does not commit or push main.
rem ------------------------------------------------------------

rem Resolve both worktrees relative to this BAT file. This keeps the
rem script independent of the USB drive letter and current directory.
for %%I in ("%~dp0vojtamaur-web") do set "MAIN=%%~fI"
for %%I in ("%~dp0vojtamaur-pages") do set "PAGES=%%~fI"
set "MESSAGE=Deploy Codeberg Pages"

if not "%~1"=="" set "MESSAGE=%~1"

echo.
echo [1/7] Checking directories...

if not exist "%MAIN%\.git" (
    echo ERROR: Git repository not found at "%MAIN%".
    exit /b 1
)

if not exist "%PAGES%\.git" (
    echo ERROR: Pages worktree not found at "%PAGES%".
    exit /b 1
)

rem Linked Git worktrees also contain absolute paths internally. Repair them
rem after the USB drive letter or parent directory has changed.
echo Repairing Git worktree links...
git -C "%MAIN%" worktree repair "%PAGES%"
if errorlevel 1 (
    echo ERROR: Could not repair the Git worktree links.
    exit /b 1
)

for /f "delims=" %%B in ('git -C "%MAIN%" branch --show-current 2^>nul') do set "MAIN_BRANCH=%%B"
if /I not "!MAIN_BRANCH!"=="main" (
    echo ERROR: "%MAIN%" is on branch "!MAIN_BRANCH!", not "main".
    exit /b 1
)

for /f "delims=" %%B in ('git -C "%PAGES%" branch --show-current 2^>nul') do set "PAGES_BRANCH=%%B"
if /I not "!PAGES_BRANCH!"=="pages" (
    echo ERROR: "%PAGES%" is on branch "!PAGES_BRANCH!", not "pages".
    exit /b 1
)

git -C "%PAGES%" remote get-url codeberg >nul 2>&1
if errorlevel 1 (
    echo ERROR: Remote "codeberg" is not configured.
    exit /b 1
)

echo [2/7] Checking main working tree...

git -C "%MAIN%" status --porcelain | findstr /r "." >nul
if not errorlevel 1 (
    echo ERROR: The main working tree has uncommitted changes.
    echo Commit or stash them before deploying.
    exit /b 1
)

echo [3/7] Building website...

pushd "%MAIN%" || exit /b 1
call npm run build
if errorlevel 1 (
    popd
    echo ERROR: Website build failed.
    exit /b 1
)
popd

if not exist "%MAIN%\dist\index.html" (
    echo ERROR: "%MAIN%\dist\index.html" was not created.
    exit /b 1
)

echo [4/7] Cleaning generated Pages worktree...

git -C "%PAGES%" reset --hard >nul
if errorlevel 1 (
    echo ERROR: Could not reset the pages worktree.
    exit /b 1
)

git -C "%PAGES%" rm -r -q --ignore-unmatch .
if errorlevel 1 (
    echo ERROR: Could not remove the previous Pages files.
    exit /b 1
)

git -C "%PAGES%" clean -fdx >nul
if errorlevel 1 (
    echo ERROR: Could not clean the pages worktree.
    exit /b 1
)

echo [5/7] Copying dist to pages...

robocopy "%MAIN%\dist" "%PAGES%" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP
if errorlevel 8 (
    echo ERROR: Robocopy failed.
    exit /b 1
)

echo [6/7] Creating deployment commit...

git -C "%PAGES%" add -A
if errorlevel 1 (
    echo ERROR: git add failed in the pages worktree.
    exit /b 1
)

git -C "%PAGES%" diff --cached --quiet
if not errorlevel 1 (
    echo No generated changes. Nothing to deploy.
    exit /b 0
)

git -C "%PAGES%" commit -m "%MESSAGE%"
if errorlevel 1 (
    echo ERROR: Could not create the Pages commit.
    exit /b 1
)

echo [7/7] Pushing Codeberg Pages...

git -C "%PAGES%" push codeberg pages
if errorlevel 1 (
    echo ERROR: Push to Codeberg Pages failed.
    exit /b 1
)

echo.
echo Codeberg Pages deployment completed successfully.
echo https://vojta_maur.codeberg.page/
exit /b 0
