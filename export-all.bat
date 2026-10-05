@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"

pushd "%~dp0" || exit /b 1

rem ===========================================================================
rem SETUP / PREFLIGHT
rem ===========================================================================
echo.
echo ============================================================
echo   VOJTAMAUR.CZ - EXPORT ALL
echo ============================================================
echo.

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js was not found in PATH.
    set "EXPORT_EXIT=10"
    goto :failed
)

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    set "EXPORT_EXIT=11"
    goto :failed
)

if not exist "dist\ALL_POSTS.txt" (
    echo [ERROR] dist\ALL_POSTS.txt was not found.
    echo Create a current standard web build first:
    echo     npm run build:web:strict
    set "EXPORT_EXIT=12"
    goto :failed
)

if not exist "dist\ALL_POSTS.json" (
    echo [ERROR] dist\ALL_POSTS.json was not found. Rebuild the site first.
    set "EXPORT_EXIT=12"
    goto :failed
)

for %%R in (
    "requirements-pdf-export.txt"
    "requirements-epub-export.txt"
    "requirements-sstv-export.txt"
    "requirements-mom-like-export.txt"
) do (
    if not exist "%%~R" (
        echo [ERROR] Missing requirements file: %%~R
        set "EXPORT_EXIT=13"
        goto :failed
    )
)

echo [SETUP 1/2] Installing/checking Python dependencies...
python -m pip install --disable-pip-version-check ^
    -r requirements-pdf-export.txt ^
    -r requirements-epub-export.txt ^
    -r requirements-sstv-export.txt ^
    -r requirements-mom-like-export.txt
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    echo.
    echo [ERROR] Python dependency installation/check failed.
    goto :failed
)

echo.
echo [SETUP 2/2] Installing/checking Playwright Chromium...
python -m playwright install chromium
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    echo.
    echo [ERROR] Playwright Chromium installation/check failed.
    goto :failed
)

rem Find Ghostscript dynamically instead of requiring one exact version.
set "GS_EXE="

where gswin64c.exe >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%G in ('where gswin64c.exe 2^>nul') do (
        if not defined GS_EXE set "GS_EXE=%%G"
    )
)

if not defined GS_EXE (
    for /d %%D in ("C:\Program Files\gs\gs*") do (
        if exist "%%~fD\bin\gswin64c.exe" set "GS_EXE=%%~fD\bin\gswin64c.exe"
    )
)

if not defined GS_EXE (
    for /d %%D in ("C:\Program Files (x86)\gs\gs*") do (
        if exist "%%~fD\bin\gswin64c.exe" set "GS_EXE=%%~fD\bin\gswin64c.exe"
    )
)

if not defined GS_EXE (
    echo.
    echo [ERROR] Ghostscript 64-bit executable gswin64c.exe was not found.
    echo The standard PDF export uses --pdf-quality ebook and requires Ghostscript.
    echo Install Ghostscript, then run this BAT again.
    set "EXPORT_EXIT=15"
    goto :failed
)

echo.
echo [OK] Node.js found.
echo [OK] Python found.
echo [OK] Python dependencies ready.
echo [OK] Playwright Chromium ready.
echo [OK] Ghostscript: !GS_EXE!

rem ===========================================================================
rem EXPORT WORKFLOW
rem ===========================================================================

rem Use one local timestamp for every artifact in this archival edition.
set "VOJTAMAUR_EXPORT_TIMESTAMP="
for /f "delims=" %%T in ('python scripts/export_naming.py') do set "VOJTAMAUR_EXPORT_TIMESTAMP=%%T"
if not defined VOJTAMAUR_EXPORT_TIMESTAMP (
    echo [ERROR] Could not create the export timestamp.
    set "EXPORT_EXIT=16"
    goto :failed
)
echo [EDITION] !VOJTAMAUR_EXPORT_TIMESTAMP!

echo.
echo [1/11] Compact English Free Creation text export
python scripts/filter-all-posts.py --language en --section volna-tvorba --format compact
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [2/11] Compact Czech Free Creation text export
python scripts/filter-all-posts.py --language cs --section volna-tvorba --format compact
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [3/11] Bilingual Morse text export
python scripts/export-site-morse.py --lang both
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [4/11] Standard archival PDF export
python scripts/export-site-pdf.py --pdf-quality ebook --image-dpi 150 --jpeg-quality 75 --ghostscript "!GS_EXE!"
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [5/11] Ultra-compact Czech PDF export
python scripts/export-site-pdf-ultra.py --lang cs --image-dpi 400
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [6/11] MoM-like Czech Free Creation PDF export
python scripts/export-site-mom-like.py --lang cs
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [7/11] MoM-like English Free Creation PDF export
python scripts/export-site-mom-like.py --lang en
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [8/11] Metaweb archival PDF export
python scripts/export-metaweb-pdf.py
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [9/11] Compact bilingual Metaweb EPUB export
python scripts/export-metaweb-epub.py --image-quality compact --gif-mode preserve
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [10/11] Compact Czech and English site EPUB exports
python scripts/export-site-epub.py --lang both --image-quality compact --gif-mode preserve
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [11/11] SSTV PNG export
python scripts/export-site-sstv.py
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo ============================================================
echo   All exports completed successfully.
echo ============================================================
popd
pause
exit /b 0

:failed
echo.
echo ============================================================
echo   Export workflow FAILED with exit code %EXPORT_EXIT%.
echo ============================================================
echo Check the error shown above.
popd
pause
exit /b %EXPORT_EXIT%
