@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"

pushd "%~dp0" || exit /b 1

echo.
echo [1/6] Compact English Free Creation text export
python scripts/filter-all-posts.py --language en --section volna-tvorba --format compact
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [2/6] Standard archival PDF export
python scripts/export-site-pdf.py --pdf-quality ebook --image-dpi 150 --jpeg-quality 75 --ghostscript "C:\Program Files\gs\gs10.07.1\bin\gswin64c.exe"
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [3/6] Ultra-compact Czech PDF export
python scripts/export-site-pdf-ultra.py --lang cs --image-dpi 400
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [4/6] Metaweb archival PDF export
python scripts/export-metaweb-pdf.py
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [5/6] Compact bilingual Metaweb EPUB export
python scripts/export-metaweb-epub.py --image-quality compact
if errorlevel 1 (
    set "EXPORT_EXIT=!ERRORLEVEL!"
    goto :failed
)

echo.
echo [6/6] Compact Czech and English site EPUB exports
python scripts/export-site-epub.py --lang both --image-quality compact
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
