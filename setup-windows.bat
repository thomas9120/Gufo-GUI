@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\windows\setup.ps1" %*
set "exit_code=%errorlevel%"
if "%exit_code%"=="0" exit /b 0
echo.
echo Gufo setup stopped. Read the message above, then run setup-windows.bat again.
pause
exit /b %exit_code%
