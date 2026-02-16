@echo off
title Garmin Wrapped Generator
color 0A

echo.
echo  +====================================================+
echo  ^|           GARMIN WRAPPED GENERATOR                ^|
echo  ^|         Your Year in Fitness Summary              ^|
echo  +====================================================+
echo.

:: Check if Python 3.13 is available (try py launcher first, then python)
echo  Checking for Python 3.13...
echo.

py -3.13 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py -3.13
    echo  Found Python 3.13 via py launcher
    goto :python_found
)

python --version 2>&1 | findstr "3.13" >nul
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    echo  Found Python 3.13
    goto :python_found
)

:: Python 3.13 not found
color 0C
echo  [ERROR] Python 3.13 is required but not found!
echo.
echo  Please install Python 3.13 from:
echo    https://www.python.org/downloads/release/python-3130/
echo.
echo  IMPORTANT: During installation, check "Add Python to PATH"
echo.
echo  Note: Python 3.14+ is NOT compatible with this script.
echo.
pause
exit /b 1

:python_found
echo.
echo  NOTE: On first run, you will be prompted to enter your
echo        Garmin Connect username and password.
echo.

:: Ask for the year
set /p YEAR="  Enter year to generate (e.g., 2024): "

:: Validate input - default to 2024 if empty
if "%YEAR%"=="" set YEAR=2024

echo.
echo  Generating Garmin Wrapped for %YEAR%...
echo  ========================================================
echo.

:: Run the script with the correct Python
%PYTHON_CMD% garmin_wrapped_2025_all.py %YEAR%

echo.
echo  ========================================================
echo.
echo  Done! Check the generated files:
echo    - garmin_wrapped_%YEAR%_report.html (styled report)
echo    - garmin_wrapped_%YEAR%_report.txt (text report)
echo.
pause
