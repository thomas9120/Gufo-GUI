# Build the official checkout using its own toolchain, presets and runtime staging.
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$GufoPath,
  [Parameter(Mandatory)][string]$VisualStudio,
  [Parameter(Mandatory)][string]$Rocm,
  [Parameter(Mandatory)][string]$Vcpkg,
  [Parameter(Mandatory)][string]$Ninja,
  [string]$Python = "python",
  [ValidateRange(1, 64)][int]$Jobs = 4
)
$ErrorActionPreference = "Stop"
$source = (Resolve-Path -LiteralPath $GufoPath).Path
foreach ($file in @("tools\windows\patch_sdk_math.py", "CMakePresets.json")) {
  if (-not (Test-Path -LiteralPath (Join-Path $source $file))) { throw "Missing upstream file $file in $source. Update official Gufo main first." }
}
# CMake serializes HIP_PATH into generated compiler files; use CMake-safe slashes.
$env:HIP_PATH = (Resolve-Path -LiteralPath $Rocm).Path.Replace('\', '/')
$env:VCPKG_ROOT = (Resolve-Path -LiteralPath $Vcpkg).Path.Replace('\', '/')
$env:ROCM_PATH = $env:HIP_PATH
$env:HIP_DEVICE_LIB_PATH = "$env:HIP_PATH/lib/llvm/amdgcn/bitcode"
# Select this SDK's helper tools and let vcvars find vswhere without a global PATH edit.
$vsInstaller = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer"
$env:PATH = "$vsInstaller;$Rocm\bin;$Rocm\lib\llvm\bin;$env:PATH"
$env:GUFO_VCVARS = Join-Path $VisualStudio "VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path -LiteralPath $env:GUFO_VCVARS)) { throw "Visual Studio C++ x64 tools were not found. Run setup-windows.bat first." }
$env:GUFO_CMAKE = (Get-Command cmake.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$env:GUFO_NINJA = (Get-Command $Ninja -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$env:GUFO_BUILD_JOBS = "$Jobs"
$env:GUFO_BUILD_DIR = Join-Path $source "build\windows-release"
$env:GUFO_POWERSHELL = (Get-Process -Id $PID).Path
& $Python (Join-Path $source "tools\windows\patch_sdk_math.py") $env:HIP_PATH
if ($LASTEXITCODE -ne 0) { throw "Upstream's SDK header patch failed (exit $LASTEXITCODE)." }
Push-Location -LiteralPath $source
try {
  & "$PSScriptRoot\build-upstream.cmd"
  if ($LASTEXITCODE -ne 0) { throw "Official Gufo build failed (exit $LASTEXITCODE). See the compiler output above." }
} finally { Pop-Location }
if (-not (Test-Path -LiteralPath (Join-Path $source "build\windows-release\gufo.exe"))) {
  throw "The build completed without producing build\windows-release\gufo.exe."
}
