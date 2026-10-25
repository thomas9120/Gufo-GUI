# Start the optional local web launcher. The first run creates an isolated venv.
param(
  [int]$Port = 8090,
  [string]$Config = "",
  [switch]$NoBrowser,
  [string]$Python = "python",
  [switch]$PrepareOnly
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath "$PSScriptRoot\..\..").Path
$environment = Join-Path $root "build\gui-env"
$venvPython = Join-Path $environment "Scripts\python.exe"
$requirements = Join-Path $root "tools\gui\requirements.txt"
$stamp = Join-Path $environment "gufo-requirements.sha256"
if (-not (Test-Path -LiteralPath $venvPython) -and $Python -eq "python") {
  $stateFile = Join-Path $root "build\windows-setup.json"
  if (Test-Path -LiteralPath $stateFile) {
    $saved = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    if ($saved.Python -and (Test-Path -LiteralPath $saved.Python)) { $Python = $saved.Python }
  }
}
if (-not (Test-Path -LiteralPath $venvPython)) {
  Write-Host "Creating the Gufo launcher environment (Python 3.10+ required)..."
  & $Python -I -c "import struct,sys; assert sys.version_info >= (3,10) and struct.calcsize('P') == 8, '64-bit Python 3.10+ is required'"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $Python -m venv $environment
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirements).Hash
$installedHash = if (Test-Path -LiteralPath $stamp) { [string](Get-Content -LiteralPath $stamp -Raw) } else { "" }
$dependenciesReady = $false
if ($installedHash.Trim() -eq $hash) {
  & $venvPython -c "import flask, waitress"
  $dependenciesReady = $LASTEXITCODE -eq 0
}
if (-not $dependenciesReady) {
  # A matching stamp does not guarantee that the installed packages are intact.
  if (Test-Path -LiteralPath $stamp) { Remove-Item -LiteralPath $stamp }
  # A cancelled first-time venv creation may leave Python present without pip.
  & $venvPython -m ensurepip --upgrade
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $venvPython -m pip install --force-reinstall -r $requirements
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $venvPython -c "import flask, waitress"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  Set-Content -LiteralPath $stamp -Value $hash
}
if ($PrepareOnly) { exit 0 }
$arguments = @((Join-Path $root "tools\gui\server.py"), "--port", "$Port")
if ($Config) { $arguments += @("--config", $Config) }
if ($NoBrowser) { $arguments += "--no-browser" }
& $venvPython @arguments
exit $LASTEXITCODE
