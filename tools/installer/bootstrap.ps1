# Find Python before the Python-based interface can run. Keep OS setup here.
$ErrorActionPreference = "Stop"
$installerArguments = @($args)
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
. "$root\tools\windows\setup.ps1"
$tools = Get-SetupTools
if (-not $tools.Python) {
  Write-Host "Gufo Setup needs 64-bit Python 3.10+. Install the pinned Python package with WinGet? [y/N]"
  if ((Read-Host) -notmatch '^(y|yes)$') { exit 2 }
  Install-SetupPackage "Python"
  $tools = Get-SetupTools
  if (-not $tools.Python) { throw "Python is still unavailable. Finish installation/restart, then rerun Gufo-Setup.cmd." }
}
& $tools.Python "$PSScriptRoot\bootstrap.py" @installerArguments
exit $LASTEXITCODE
