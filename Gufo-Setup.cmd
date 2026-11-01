@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\installer\bootstrap.ps1" %*
set "result=%errorlevel%"
if "%result%"=="0" exit /b 0
if "%result%"=="2" exit /b 2
echo.
echo Gufo Setup stopped. Read the message above and run this file again.
if "%~1"=="" pause
exit /b %result%
