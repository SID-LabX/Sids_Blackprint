@echo off
setlocal enabledelayedexpansion
title Albion Market Packet Automator (In-Place)

:: -------------------------------------------------------------
:: CONFIGURATION DIRECTORIES
:: -------------------------------------------------------------
set "BASE_DIR=C:\Users\SID\Desktop\albion"
set "SAVES_DIR=%BASE_DIR%\saves_here"
set "ITEMS_JSON=%BASE_DIR%\items.json"

set "SCRIPT_ERASE=%BASE_DIR%\event_erase.py"
set "SCRIPT_SHEET=%BASE_DIR%\build_market_sheet.py"
set "SCRIPT_MD=%BASE_DIR%\market_json_summary.py"

echo ============================================================
echo         ALBION MARKET PIPELINE (SAVES_HERE IN-PLACE)
echo ============================================================

:: Check if user dragged a specific file or folder
if not "%~1"=="" (
    if exist "%~1\*" (
        set "TARGET_DIR=%~1"
        call :ProcessFolder "!TARGET_DIR!"
    ) else (
        call :ProcessSingleFile "%~1"
    )
    goto :Finish
)

:: Default: Process all raw JSON files inside saves_here
call :ProcessFolder "%SAVES_DIR%"
goto :Finish

:: -------------------------------------------------------------
:: SUBROUTINE: PROCESS FOLDER
:: -------------------------------------------------------------
:ProcessFolder
set "SCAN_FOLDER=%~1"
echo [*] Scanning directory: "%SCAN_FOLDER%" for raw packet files...

set /a count=0
for %%F in ("%SCAN_FOLDER%\*.json") do (
    :: Safely skip any files that are already cleaned, stream, or summary files
    echo "%%~nxF" | findstr /i "_clean _stream _summary" >nul
    if errorlevel 1 (
        set /a count+=1
        call :ProcessSingleFile "%%~fF"
    )
)

if %count%==0 (
    echo [!] No new raw packet JSON files found to process.
)
exit /b

:: -------------------------------------------------------------
:: SUBROUTINE: PROCESS SINGLE FILE PIPELINE
:: -------------------------------------------------------------
:ProcessSingleFile
set "RAW_FILE=%~1"
set "FILE_NAME=%~n1"
set "FILE_EXT=%~x1"
set "FILE_DIR=%~dp1"

echo.
echo ------------------------------------------------------------
echo [*] Processing File: %FILE_NAME%%FILE_EXT%
echo ------------------------------------------------------------

:: STEP 1: Run event_erase.py
echo [1/4] Stripping EVENT packets...
python "%SCRIPT_ERASE%" "%RAW_FILE%"
if errorlevel 1 (
    echo [!] Error during event_erase.py! Aborting this file.
    exit /b
)

set "CLEAN_FILE=%FILE_DIR%%FILE_NAME%_clean%FILE_EXT%"
if not exist "%CLEAN_FILE%" (
    echo [!] Cleaned file not found: "%CLEAN_FILE%"
    exit /b
)

:: Delete original heavy raw packet file
echo [2/4] Deleting heavy raw packet dump...
del /f /q "%RAW_FILE%"

:: Rename the clean stream file right inside saves_here
set "SAVED_STREAM=%FILE_DIR%%FILE_NAME%_stream.json"
move /y "%CLEAN_FILE%" "%SAVED_STREAM%" >nul

:: STEP 2: Run build_market_sheet.py
echo [3/4] Building Market Sheet and L2 Orderbook...
python "%SCRIPT_SHEET%" "%SAVED_STREAM%" -db "%ITEMS_JSON%" -o "%FILE_DIR%%FILE_NAME%_summary"
if errorlevel 1 (
    echo [!] Error during build_market_sheet.py!
    exit /b
)

:: STEP 3: Run market_json_summary.py to generate clean .md
echo [4/4] Generating Compact L2 Depth Dossier (.md)...
python "%SCRIPT_MD%" "%FILE_DIR%%FILE_NAME%_summary.json" "%FILE_DIR%%FILE_NAME%_dossier.md"
if errorlevel 1 (
    echo [!] Error during market_json_summary.py!
    exit /b
)

echo [+] Successfully completed: %FILE_NAME%
exit /b

:: -------------------------------------------------------------
:: FINISH
:: -------------------------------------------------------------
:Finish
echo.
echo ============================================================
echo [SUCCESS] All files processed and saved in saves_here!
echo ============================================================
pause