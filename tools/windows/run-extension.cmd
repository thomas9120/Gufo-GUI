@echo off
rem Run `gufo.exe extension ...` inside the saved MSVC / TheRock / vcpkg toolchain environment.
setlocal
set "GUFO_SELECTED_VCPKG=%VCPKG_ROOT%"
set "GUFO_SELECTED_HIP=%HIP_PATH%"
call "%GUFO_VCVARS%" >nul
if errorlevel 1 exit /b %errorlevel%
set "VCPKG_ROOT=%GUFO_SELECTED_VCPKG%"
set "HIP_PATH=%GUFO_SELECTED_HIP%"
"%GUFO_EXE%" extension %*
exit /b %errorlevel%
