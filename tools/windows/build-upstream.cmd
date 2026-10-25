@echo off
rem Environment variables keep tool paths with spaces and ampersands quoted.
setlocal
rem vcvars64 can replace VCPKG_ROOT with Visual Studio's bundled checkout.
set "GUFO_SELECTED_VCPKG=%VCPKG_ROOT%"
set "GUFO_SELECTED_HIP=%HIP_PATH%"
call "%GUFO_VCVARS%" >nul
if errorlevel 1 exit /b %errorlevel%
set "VCPKG_ROOT=%GUFO_SELECTED_VCPKG%"
set "HIP_PATH=%GUFO_SELECTED_HIP%"
rem Launcher installs do not need the upstream developer warning stream.
call "%GUFO_CMAKE%" --preset windows-release "-DCMAKE_MAKE_PROGRAM=%GUFO_NINJA%" -DGUFO_ENABLE_WARNINGS=OFF
if errorlevel 1 exit /b %errorlevel%
call "%GUFO_CMAKE%" --build --preset windows-release --target gufo --parallel %GUFO_BUILD_JOBS%
if errorlevel 1 exit /b %errorlevel%
"%GUFO_POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0stage-runtime.ps1" -BuildPath "%GUFO_BUILD_DIR%"
exit /b %errorlevel%
