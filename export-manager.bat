@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
pushd "%~dp0" || exit /b 1
where python.exe >nul 2>&1
if not errorlevel 1 (
    python.exe -B -c "import sys; sys.path.insert(0, 'scripts'); import tkinter; import export_manager_core; import export_manager_help; import export_manager_tasks"
    if errorlevel 1 (
        echo [CHYBA] Chybi soucasti manageru nebo Python s Tkinterem. Viz chyba vyse.
        pause
        popd
        exit /b 1
    )
)
where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "" pythonw.exe -B "%~dp0scripts\export-manager.py"
    popd
    exit /b 0
)
where python.exe >nul 2>&1
if not errorlevel 1 (
    python.exe -B "%~dp0scripts\export-manager.py"
    if errorlevel 1 pause
    popd
    exit /b
)
echo [CHYBA] Python nebyl nalezen. Nainstalujte Python 3.10 nebo novejsi s Tkinterem.
pause
popd
exit /b 1
