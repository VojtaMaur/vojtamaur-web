@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo SSTV PD120 encoder
echo ========================================
echo.

set "ENCODER="

if defined OPEN_SSTV_ENCODER (
    if exist "%OPEN_SSTV_ENCODER%" set "ENCODER=%OPEN_SSTV_ENCODER%"
)

if not defined ENCODER (
    for /f "delims=" %%E in ('where open-sstv-encode.exe 2^>nul') do (
        if not defined ENCODER set "ENCODER=%%E"
    )
)

if not defined ENCODER (
    if exist "%~dp0.venv\Scripts\open-sstv-encode.exe" (
        set "ENCODER=%~dp0.venv\Scripts\open-sstv-encode.exe"
    )
)

if not defined ENCODER (
    if exist "%~dp0Open-SSTV\.venv\Scripts\open-sstv-encode.exe" (
        set "ENCODER=%~dp0Open-SSTV\.venv\Scripts\open-sstv-encode.exe"
    )
)

if not defined ENCODER (
    if exist "%USERPROFILE%\Downloads\Open-SSTV\.venv\Scripts\open-sstv-encode.exe" (
        set "ENCODER=%USERPROFILE%\Downloads\Open-SSTV\.venv\Scripts\open-sstv-encode.exe"
    )
)

if not defined ENCODER (
    echo CHYBA: open-sstv-encode.exe nebyl nalezen.
    echo.
    echo Hledal jsem v PATH a v beznych .venv umistenich.
    echo Pokud je Open-SSTV jinde, lze pred spustenim nastavit:
    echo set OPEN_SSTV_ENCODER=C:\cesta\k\open-sstv-encode.exe
    echo.
    pause
    exit /b 1
)

echo Encoder: "%ENCODER%"
echo.

if not exist "input_images" (
    echo CHYBA: chybi slozka input_images
    pause
    exit /b 1
)

if not exist "input_wav" mkdir "input_wav"

set "FOUND=0"

for %%F in ("input_images\*.png") do (
    if exist "%%~fF" (
        set "FOUND=1"

        if exist "input_wav\%%~nF.wav" (
            echo SKIP: %%~nxF
        ) else (
            echo Encoding: %%~nxF
            "%ENCODER%" "%%~fF" --mode pd_120 -o "input_wav\%%~nF.wav"

            if errorlevel 1 (
                echo.
                echo CHYBA pri zpracovani: %%~nxF
                pause
                exit /b 1
            )
        )
    )
)

if "%FOUND%"=="0" (
    echo CHYBA: ve slozce input_images nejsou zadne PNG soubory.
    pause
    exit /b 1
)

echo.
echo ========================================
echo HOTOVO
echo WAV soubory jsou v input_wav
echo ========================================
pause
