# Fast-forward official Gufo main and rebuild; the standalone GUI stays separate.
[CmdletBinding()]
param(
  [string]$GufoPath = "",
  [string]$Rocm = "",
  [string]$Vcpkg = "",
  [string]$Ninja = "",
  [ValidateRange(1, 64)][int]$Jobs = 4
)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\setup.ps1" -GufoPath $GufoPath -Rocm $Rocm -Vcpkg $Vcpkg -Jobs $Jobs

function Invoke-WindowsUpdate {
  $tools = Get-SetupTools
  if ($Ninja) { $tools.Ninja = (Get-Command $Ninja -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source }
  $missing = @(@("Git", "VS", "CMake", "Ninja", "Python", "Rocm", "Vcpkg") | Where-Object { -not $tools.$_ })
  if ($missing.Count -or -not (Test-Path -LiteralPath "$($tools.Vcpkg)\vcpkg.exe")) {
    throw "Build prerequisites are missing ($($missing -join ', ')). Run setup-windows.bat first."
  }
  Assert-EngineStopped
  Assert-GufoSource $tools.Git
  Write-Host "Updating official Gufo main at $engineRoot..." -ForegroundColor Cyan
  Invoke-SetupCommand $tools.Git @("-C", $engineRoot, "pull", "--ff-only", "--no-rebase", "--no-autostash", $repository, "main")
  Assert-EngineStopped
  $tools.Vcpkg = Initialize-SetupVcpkg $tools.Git $tools.Vcpkg
  Save-SetupTools $tools
  $env:PATH = "$(Split-Path $tools.Git);$(Split-Path $tools.CMake);$(Split-Path $tools.Ninja);$(Split-Path $tools.Python);$env:PATH"
  $shell = (Get-Process -Id $PID).Path
  Invoke-SetupCommand $shell @("-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "$PSScriptRoot\build.ps1",
    "-GufoPath", $engineRoot, "-VisualStudio", $tools.VS, "-Python", $tools.Python, "-Jobs", "$Jobs", "-Rocm", $tools.Rocm, "-Vcpkg", $tools.Vcpkg, "-Ninja", $tools.Ninja)
  $engine = Join-Path $engineRoot "build\windows-release\gufo.exe"
  Invoke-SetupCommand $engine @("--version")
  Invoke-SetupCommand $engine @("diagnose", "--section", "gpu")
  Write-Host "`nUpdate complete: $engine" -ForegroundColor Green
  Write-Host "Open launch-gui.bat. Saved presets are preserved."
}

if ($MyInvocation.InvocationName -ne ".") {
  try { Invoke-WindowsUpdate } catch {
    Write-Host "`nUpdate stopped: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
  }
}
