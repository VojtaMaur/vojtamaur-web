@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"

pushd "%~dp0" || exit /b 1

echo.
echo [1/9] Structured JSON-LD article export
node scripts/export-site-json.mjs
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [2/9] Compact English Free Creation text export
python scripts/filter-all-posts.py --language en --section volna-tvorba --format compact
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [3/9] Compact Czech Free Creation text export
python scripts/filter-all-posts.py --language cs --section volna-tvorba --format compact
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [4/9] Standard archival PDF export
python scripts/export-site-pdf.py --pdf-quality ebook --image-dpi 150 --jpeg-quality 75 --ghostscript "C:\Program Files\gs\gs10.07.1\bin\gswin64c.exe"
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [5/9] Ultra-compact Czech PDF export
python scripts/export-site-pdf-ultra.py --lang cs --image-dpi 400
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [6/9] Metaweb archival PDF export
python scripts/export-metaweb-pdf.py
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [7/9] Compact bilingual Metaweb EPUB export
python scripts/export-metaweb-epub.py --image-quality compact --gif-mode preserve
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [8/9] Compact Czech and English site EPUB exports
python scripts/export-site-epub.py --lang both --image-quality compact --gif-mode preserve
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [9/9] SSTV PNG export
python scripts/export-site-sstv.py
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

popd
echo.
echo All exports completed successfully.
exit /b 0

:failed
popd
echo.
echo Export workflow failed with exit code %EXPORT_EXIT%.
exit /b %EXPORT_EXIT%
