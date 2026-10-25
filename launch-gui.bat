@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\windows\gui.ps1" %*
set "exit_code=%errorlevel%"
if "%exit_code%"=="0" exit /b 0
echo.
echo Gufo launcher stopped with an error. See the message above.
pause
exit /b %exit_code%
