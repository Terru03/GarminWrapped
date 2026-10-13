@echo off
setlocal
title Garmin Wrapped Generator

rem Optional full executable path for portable Python installations.
if defined GARMIN_WRAPPED_PYTHON goto :override
if exist "%~dp0.venv\Scripts\python.exe" goto :local
py -3.14 --version >nul 2>&1
if not errorlevel 1 goto :py314
py -3.13 --version >nul 2>&1
if not errorlevel 1 goto :py313
python --version >nul 2>&1
if not errorlevel 1 goto :python
echo [ERROR] Install Python 3.13 or 3.14, or set GARMIN_WRAPPED_PYTHON to its full executable path.
exit /b 1

:override
"%GARMIN_WRAPPED_PYTHON%" "%~dp0launch_garmin_wrapped.py" %*
exit /b %errorlevel%

:local
"%~dp0.venv\Scripts\python.exe" "%~dp0launch_garmin_wrapped.py" %*
exit /b %errorlevel%

:py314
py -3.14 "%~dp0launch_garmin_wrapped.py" %*
exit /b %errorlevel%

:py313
py -3.13 "%~dp0launch_garmin_wrapped.py" %*
exit /b %errorlevel%

:python
python "%~dp0launch_garmin_wrapped.py" %*
exit /b %errorlevel%
