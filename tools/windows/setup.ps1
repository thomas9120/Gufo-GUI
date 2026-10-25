# Guided source setup. Dot-source to exercise helpers without installing anything.
[CmdletBinding()]
param(
  [string]$GufoPath = "",
  [string]$Rocm = "",
  [string]$Vcpkg = "",
  [switch]$CheckOnly,
  [string]$PlanJson = "",
  [switch]$Yes,
  [switch]$NoLaunch,
  [ValidateRange(1, 64)][int]$Jobs = 4
)
$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$stateFile = Join-Path $root "build\windows-setup.json"
$repository = "https://github.com/gufo-org/gufo.git"
if (-not $GufoPath -and (Test-Path -LiteralPath $stateFile)) {
  $GufoPath = (Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json).GufoPath
}
if (-not $GufoPath) { $GufoPath = Join-Path $root "gufo" }
$engineRoot = [IO.Path]::GetFullPath((Join-Path $GufoPath "."))
if ($engineRoot -eq $root) { throw "Gufo needs a separate folder from the GUI repository. Use -GufoPath or the default gufo subfolder." }
$deps = Join-Path $env:LOCALAPPDATA "Gufo\dependencies"
$rockVersion = "10.0.0"
$rockHash = "1293927b06b3b8d4bd7e0265823fb998bc9e0d83c68f33dcfa5d32663b30ce38"
$packages = [ordered]@{
  Git = @("Git.Git", "2.55.0.3")
  VS = @("Microsoft.VisualStudio.BuildTools", "18.8.0")
  CMake = @("Kitware.CMake", "4.4.0")
  Ninja = @("Ninja-build.Ninja", "1.13.2")
  Python = @("Python.Python.3.14", "3.14.6")
}

function Invoke-SetupCommand([string]$File, [string[]]$Arguments) {
  # Windows PowerShell represents native stderr as ErrorRecords, even on success.
  $previous = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    & $File @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $previous }
  if ($code -ne 0) {
    throw "$File failed (exit $code). See the setup log. If an installer requests a restart, restart Windows and rerun setup."
  }
}

function Find-Program([string[]]$Candidates, [string[]]$VersionArgs, [version]$Minimum) {
  foreach ($candidate in $Candidates) {
    if (-not $candidate) { continue }
    $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command -or $command.Source -match '\\WindowsApps\\python[0-9.]*\.exe$') { continue }
    try {
      $output = & $command.Source @VersionArgs 2>$null
      if ($LASTEXITCODE -eq 0 -and "$output" -match '(\d+\.\d+(?:\.\d+)?)' -and [version]$Matches[1] -ge $Minimum) {
        return $command.Source
      }
    } catch { continue }
  }
}

function Find-VisualStudio([switch]$Any) {
  $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
  if (-not (Test-Path -LiteralPath $vswhere)) { return }
  $arguments = @("-latest", "-products", "*", "-property", "installationPath")
  if (-not $Any) { $arguments += @("-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64") }
  & $vswhere @arguments | Select-Object -First 1
}

function Test-WindowsSdk {
  $sdk = "${env:ProgramFiles(x86)}\Windows Kits\10\Include"
  [bool](Get-ChildItem -LiteralPath $sdk -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^10\.' -and (Test-Path -LiteralPath (Join-Path $_.FullName "um\Windows.h")) } |
    Select-Object -First 1)
}

function Test-Rock([string]$Path) {
  if (-not $Path) { return $false }
  $version = Join-Path $Path ".info\version"
  (Test-Path -LiteralPath $version) -and
    ((Get-Content -LiteralPath $version -TotalCount 1).Trim() -eq $rockVersion) -and
    ((Test-Path -LiteralPath (Join-Path $Path "lib\llvm\bin\clang-cl.exe")) -or
     (Test-Path -LiteralPath (Join-Path $Path "lib\llvm\bin\amdclang-cl.exe")))
}

function Get-SetupTools {
  $saved = @{}
  if (Test-Path -LiteralPath $stateFile) {
    try { $saved = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json } catch {
      throw "Cannot read saved tool paths in $stateFile. Rename that file and rerun setup to detect tools again. GUI settings are separate."
    }
  }
  $vs = Find-VisualStudio
  $cmakeRoot = if ($vs) { Join-Path $vs "Common7\IDE\CommonExtensions\Microsoft\CMake" } else { "" }
  $pythonCandidates = @($saved.Python, (Join-Path $root "build\gui-env\Scripts\python.exe"), "python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe", "$env:ProgramFiles\Python314\python.exe")
  # Discover installs off PATH without invoking py's install-manager auto-download.
  foreach ($key in Get-ChildItem 'HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore' -ErrorAction SilentlyContinue) {
    $install = Get-ItemProperty -LiteralPath "$($key.PSPath)\InstallPath" -ErrorAction SilentlyContinue
    if ($install.ExecutablePath) { $pythonCandidates += $install.ExecutablePath }
  }
  $tools = [ordered]@{
    Git = Find-Program @($saved.Git, "git.exe", "$env:ProgramFiles\Git\cmd\git.exe") @("--version") "2.0"
    VS = $vs
    CMake = Find-Program @($saved.CMake, "cmake.exe", "$env:ProgramFiles\CMake\bin\cmake.exe", "$cmakeRoot\CMake\bin\cmake.exe") @("--version") "3.29"
    Ninja = Find-Program @($saved.Ninja, "ninja.exe", "C:\tools\ninja\ninja.exe", "$cmakeRoot\Ninja\ninja.exe") @("--version") "1.10"
    Python = Find-Program $pythonCandidates @("-I", "-c", "import struct,sys; assert struct.calcsize('P') == 8; print('.'.join(map(str,sys.version_info[:3])))") "3.10"
    Rocm = ""
    Vcpkg = ""
    GufoPath = $engineRoot
  }
  if (-not (Test-WindowsSdk)) { $tools.VS = $null }
  if ($Rocm -and -not (Test-Rock $Rocm)) { throw "-Rocm must point to a complete TheRock $rockVersion installation." }
  foreach ($path in @($Rocm, $saved.Rocm, $env:HIP_PATH, "C:\TheRock\build")) {
    if (Test-Rock $path) { $tools.Rocm = [IO.Path]::GetFullPath($path); break }
  }
  $managedRock = Join-Path $deps "therock-$rockVersion"
  if (-not $tools.Rocm -and (Test-Path -LiteralPath "$managedRock\.gufo-complete")) {
    foreach ($path in @($managedRock, "$managedRock\build", "$managedRock\rocm")) {
      if (Test-Rock $path) { $tools.Rocm = $path; break }
    }
  }
  if ($Vcpkg -and -not (Test-Path -LiteralPath "$Vcpkg\bootstrap-vcpkg.bat")) { throw "-Vcpkg must point to a vcpkg checkout." }
  foreach ($path in @($Vcpkg, $saved.Vcpkg, $env:VCPKG_ROOT, "C:\vcpkg")) {
    if ($path -and (Test-Path -LiteralPath "$path\bootstrap-vcpkg.bat")) {
      $tools.Vcpkg = [IO.Path]::GetFullPath($path); break
    }
  }
  [pscustomobject]$tools
}

function Assert-SetupMachine {
  $os = Get-CimInstance Win32_OperatingSystem
  if (-not [Environment]::Is64BitProcess -or [int]$os.BuildNumber -lt 22000 -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "Use 64-bit Windows 11 on AMD Strix Halo. Run setup-windows.bat from Explorer."
  }
  $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
  if ($cpu.Name -notmatch 'Ryzen\s+AI\s+MAX') {
    throw "This setup targets AMD Ryzen AI Max (Strix Halo/gfx1151). Detected: $($cpu.Name)"
  }
  Write-Host "Computer: $($cpu.Name), $($os.Caption)"
  Write-Host "Install the AMD graphics driver first. Model/context capacity depends on available WDDM memory budgets."
}

function Assert-EngineStopped {
  $engine = Join-Path $engineRoot "build\windows-release\gufo.exe"
  foreach ($process in @(Get-Process gufo -ErrorAction SilentlyContinue)) {
    if (-not $process.Path -or $process.Path -eq $engine) {
      throw "Gufo is running (PID $($process.Id)). Stop it in the launcher before setup can rebuild it."
    }
  }
}

function Install-SetupPackage([string]$Name) {
  $package = $packages[$Name]
  Write-Host "Installing $Name ($($package[1]))..." -ForegroundColor Cyan
  if ($Name -eq "VS" -and (Find-VisualStudio -Any)) {
    # Installing an already-present package through WinGet would skip missing components.
    $vs = Find-VisualStudio -Any
    $installer = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\setup.exe"
    $arguments = "modify --installPath `"$vs`" --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --add Microsoft.VisualStudio.Component.Windows11SDK.26100 --passive --norestart"
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -Verb RunAs -Wait -PassThru -WindowStyle Hidden -WorkingDirectory $root
    if ($process.ExitCode -ne 0) { throw "Visual Studio returned $($process.ExitCode). Finish installation/restart if requested, then rerun setup." }
  } else {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) { throw "Install/update Microsoft's App Installer from https://aka.ms/getwinget, then rerun setup. Manual prerequisites: README.md" }
    $arguments = @("install", "--id", $package[0], "--version", $package[1], "--exact", "--source", "winget", "--architecture", "x64", "--accept-source-agreements")
    if ($Name -eq "VS") {
      $arguments += @("--override", "--wait --passive --norestart --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --add Microsoft.VisualStudio.Component.Windows11SDK.26100")
    }
    if ($Name -eq "Python") { $arguments += @("--scope", "user") }
    Invoke-SetupCommand $winget.Source $arguments
  }
  # Installers may update the registry PATH without updating this running shell.
  $env:PATH = "$env:PATH;$([Environment]::GetEnvironmentVariable('PATH', 'Machine'));$([Environment]::GetEnvironmentVariable('PATH', 'User'))"
}

function Get-VerifiedDownload([string]$Url, [string]$Destination, [string]$Sha256) {
  if (Test-Path -LiteralPath $Destination) {
    if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -eq $Sha256) { return }
    throw "Cached download has the wrong checksum. Delete '$Destination' and rerun setup."
  }
  New-Item -ItemType Directory -Force -Path (Split-Path $Destination) | Out-Null
  $partial = "$Destination.partial"
  if (-not (Test-Path -LiteralPath $partial) -or (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $Sha256) {
    Invoke-SetupCommand curl.exe @("--fail", "--location", "--retry", "3", "--continue-at", "-", "--output", $partial, $Url)
  }
  if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $Sha256) {
    Remove-Item -LiteralPath $partial
    throw "Download checksum failed; the incomplete/corrupt download was removed. Rerun setup to retry."
  }
  Move-Item -LiteralPath $partial -Destination $Destination
}

function Install-SetupRock {
  $archive = Join-Path $deps "downloads\therock-dist-windows-gfx1151-$rockVersion.tar.gz"
  Write-Host "Downloading/verifying TheRock $rockVersion GPU libraries..." -ForegroundColor Cyan
  Get-VerifiedDownload "https://github.com/endyjasmi/gufo/releases/download/toolchain/therock-$rockVersion/therock-dist-windows-gfx1151-$rockVersion.tar.gz" $archive $rockHash
  $destination = Join-Path $deps "therock-$rockVersion"
  New-Item -ItemType Directory -Force -Path $destination | Out-Null
  Write-Host "Extracting TheRock. Completed downloads are reused if setup is interrupted."
  Invoke-SetupCommand tar.exe @("-xf", $archive, "-C", $destination)
  foreach ($path in @($destination, "$destination\build", "$destination\rocm")) {
    if (Test-Rock $path) {
      Set-Content -LiteralPath "$destination\.gufo-complete" -Value $rockHash
      return $path
    }
  }
  throw "TheRock extracted, but its expected runtime/compiler files were not found in $destination."
}

function Initialize-SetupVcpkg([string]$Git, [string]$Existing) {
  $revision = (Get-Content -LiteralPath (Join-Path $engineRoot "vcpkg.json") -Raw | ConvertFrom-Json).'builtin-baseline'
  if ($revision -notmatch '^[0-9a-f]{40}$') { throw "vcpkg.json has no valid pinned baseline." }
  if ($Existing) { $path = $Existing } else {
    $path = Join-Path $deps "vcpkg-$($revision.Substring(0, 12))"
    if (-not (Test-Path -LiteralPath "$path\.git")) {
      # Upstream's manifest resolves its baseline through vcpkg history.
      Invoke-SetupCommand $Git @("clone", "https://github.com/microsoft/vcpkg.git", $path)
    }
    $remotes = & $Git -C $path remote
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect the vcpkg checkout at $path." }
    if ($remotes -notcontains "origin") { Invoke-SetupCommand $Git @("-C", $path, "remote", "add", "origin", "https://github.com/microsoft/vcpkg.git") }
    $remote = & $Git -C $path config --get remote.origin.url
    if ($LASTEXITCODE -ne 0 -or $remote -ne "https://github.com/microsoft/vcpkg.git") { throw "Unexpected vcpkg remote in $path; inspect it before rerunning setup." }
    $changes = & $Git -C $path status --porcelain
    if ($LASTEXITCODE -ne 0 -or $changes) { throw "Local changes exist in $path; setup will not overwrite them." }
    Invoke-SetupCommand $Git @("-C", $path, "fetch", "origin")
    Invoke-SetupCommand $Git @("-C", $path, "checkout", "--detach", $revision)
  }
  $shallow = & $Git -C $path rev-parse --is-shallow-repository
  if ($LASTEXITCODE -ne 0) { throw "Cannot inspect vcpkg history at $path." }
  if ($shallow -eq "true") { Invoke-SetupCommand $Git @("-C", $path, "fetch", "--unshallow", "origin") }
  # A reused clone may predate the baseline required by a newer Gufo checkout.
  & $Git -C $path rev-parse --verify --quiet "${revision}^{commit}" | Out-Null
  if ($LASTEXITCODE -ne 0) { Invoke-SetupCommand $Git @("-C", $path, "fetch", "origin", $revision) }
  if (-not (Test-Path -LiteralPath "$path\vcpkg.exe")) {
    Invoke-SetupCommand "$path\bootstrap-vcpkg.bat" @("-disableMetrics")
  }
  if (-not (Test-Path -LiteralPath "$path\vcpkg.exe")) { throw "vcpkg bootstrap did not produce vcpkg.exe in $path." }
  return $path
}

function Assert-GufoSource([string]$Git) {
  if (-not (Test-Path -LiteralPath (Join-Path $engineRoot ".git"))) {
    throw "No Gufo checkout at $engineRoot. Run setup-windows.bat first."
  }
  $top = & $Git -C $engineRoot rev-parse --show-toplevel
  if ($LASTEXITCODE -ne 0 -or [IO.Path]::GetFullPath($top) -ne $engineRoot) { throw "GufoPath must be the root of its own Git checkout." }
  $remote = & $Git -C $engineRoot config --get remote.origin.url
  if ($LASTEXITCODE -ne 0 -or $remote -notmatch '^(https://github\.com/gufo-org/gufo(?:\.git)?/?|git@github\.com:gufo-org/gufo(?:\.git)?)$') {
    throw "The checkout at $engineRoot is not official gufo-org/gufo. Choose a separate folder with -GufoPath; existing forks are not converted."
  }
  $branch = & $Git -C $engineRoot symbolic-ref --quiet --short HEAD
  if ($LASTEXITCODE -ne 0 -or $branch -ne "main") { throw "Check out main in $engineRoot before setup or update." }
  $changes = & $Git -C $engineRoot status --porcelain --untracked-files=all
  if ($LASTEXITCODE -ne 0 -or $changes) { throw "The Gufo checkout has local changes or untracked files. Commit, stash or move them before setup/update." }
}

function Initialize-GufoSource([string]$Git) {
  if (-not (Test-Path -LiteralPath $engineRoot)) {
    Invoke-SetupCommand $Git @("clone", "--branch", "main", "--single-branch", $repository, $engineRoot)
  } elseif (-not (Test-Path -LiteralPath (Join-Path $engineRoot ".git")) -and
            -not (Get-ChildItem -LiteralPath $engineRoot -Force)) {
    Invoke-SetupCommand $Git @("clone", "--branch", "main", "--single-branch", $repository, $engineRoot)
  }
  Assert-GufoSource $Git
}

function Save-SetupTools($Tools) {
  New-Item -ItemType Directory -Force -Path (Split-Path $stateFile) | Out-Null
  [IO.File]::WriteAllText("$stateFile.tmp", ($Tools | ConvertTo-Json))
  if (Test-Path -LiteralPath $stateFile) { [IO.File]::Replace("$stateFile.tmp", $stateFile, [NullString]::Value) }
  else { [IO.File]::Move("$stateFile.tmp", $stateFile) }
}

function Get-SetupSpace {
  foreach ($driveRoot in @($root, $engineRoot, $deps, $env:ProgramFiles) | ForEach-Object { [IO.Path]::GetPathRoot($_) } | Select-Object -Unique) {
    $drive = [IO.DriveInfo]::new($driveRoot)
    [pscustomobject]@{ Root = $drive.RootDirectory.FullName; FreeGiB = [math]::Round($drive.AvailableFreeSpace / 1GB, 1) }
  }
}

function Assert-SetupSpace([bool]$FreshInstall) {
  $required = if ($FreshInstall) { 25 } else { 5 }
  foreach ($entry in Get-SetupSpace) {
    Write-Host "  Free space on $($entry.Root): $($entry.FreeGiB) GiB"
    if ($entry.FreeGiB -lt $required) { throw "Keep at least $required GiB free for setup/build files (models need additional space)." }
  }
}

function Write-SetupPlan($Tools, [object[]]$Missing, [string]$Path) {
  # The graphical installer renders this instead of re-deriving the plan.
  $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
  $os = Get-CimInstance Win32_OperatingSystem
  $plan = [ordered]@{
    schema = 1
    root = $root
    gufoPath = $engineRoot
    repository = $repository
    jobs = $Jobs
    machine = [ordered]@{
      cpu = ([string]$cpu.Name).Trim()
      os = ([string]$os.Caption).Trim()
      build = [int]$os.BuildNumber
      ramGiB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 0)
    }
    space = @(Get-SetupSpace | ForEach-Object { [ordered]@{ root = $_.Root; freeGiB = $_.FreeGiB } })
    packages = @($packages.Keys | ForEach-Object {
      [ordered]@{
        name = $_
        wingetId = $packages[$_][0]
        version = $packages[$_][1]
        path = [string]$Tools.$_
        action = $(if ($Tools.$_) { "reuse" } else { "install" })
      }
    })
    rock = [ordered]@{ version = $rockVersion; path = [string]$Tools.Rocm; action = $(if ($Tools.Rocm) { "reuse" } else { "download" }) }
    vcpkg = [ordered]@{ path = [string]$Tools.Vcpkg; action = $(if ($Tools.Vcpkg) { "reuse" } else { "prepare" }) }
    missing = @($Missing)
  }
  $directory = Split-Path -Parent $Path
  if ($directory) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
  [IO.File]::WriteAllText($Path, ($plan | ConvertTo-Json -Depth 5))
}

function Invoke-WindowsSetup {
  Assert-SetupMachine
  Assert-EngineStopped
  $tools = Get-SetupTools
  $missing = @($packages.Keys | Where-Object { -not $tools.$_ })
  if ($tools.Git -and (Test-Path -LiteralPath (Join-Path $engineRoot ".git"))) { Assert-GufoSource $tools.Git }
  Write-Host "`nGufo setup plan" -ForegroundColor Cyan
  Write-Host "  Official source: $repository (main) -> $engineRoot"
  foreach ($name in $packages.Keys) {
    if ($tools.$name) { Write-Host "  Reuse $name`: $($tools.$name)" }
    else { Write-Host "  Install $name`: $($packages[$name] -join ' ')" }
  }
  Write-Host $(if ($tools.Rocm) { "  Reuse TheRock: $($tools.Rocm)" } else { "  Download TheRock $rockVersion to $deps" })
  Write-Host $(if ($tools.Vcpkg) { "  Reuse vcpkg: $($tools.Vcpkg)" } else { "  Prepare pinned vcpkg under $deps" })
  Write-Host "  Build Gufo, verify GPU startup, prepare the GUI. Existing GUI settings are preserved."
  Assert-SetupSpace ([bool]($missing.Count -or -not $tools.Rocm))
  if ($CheckOnly) {
    if ($PlanJson) { Write-SetupPlan $tools $missing $PlanJson }
    Write-Host "Preview only; nothing installed or changed."
    return
  }
  if (-not $Yes -and (Read-Host "Continue with this plan? Installers may request Windows permission and license acceptance [y/N]") -notmatch '^(y|yes)$') {
    Write-Host "Setup cancelled. Nothing installed."
    return
  }
  New-Item -ItemType Directory -Force -Path (Join-Path $root "build") | Out-Null
  $log = Join-Path $root ("build\setup-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
  Start-Transcript -Path $log | Out-Null
  try {
    Write-Host "Detailed setup log: $log"
    Save-SetupTools $tools
    foreach ($name in $missing) {
      Install-SetupPackage $name
      $tools = Get-SetupTools
      if (-not $tools.$name) { throw "$name is still unavailable. Finish its installer/restart if requested, then rerun setup. See README.md for manual installation." }
      Save-SetupTools $tools
    }
    Initialize-GufoSource $tools.Git
    if (-not $tools.Rocm) { $tools.Rocm = Install-SetupRock; Save-SetupTools $tools }
    Write-Host "Preparing vcpkg dependencies..." -ForegroundColor Cyan
    $tools.Vcpkg = Initialize-SetupVcpkg $tools.Git $tools.Vcpkg
    Save-SetupTools $tools
    $env:PATH = "$(Split-Path $tools.Git);$(Split-Path $tools.CMake);$(Split-Path $tools.Ninja);$(Split-Path $tools.Python);$env:PATH"
    $shell = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path -LiteralPath $shell)) { $shell = Join-Path $PSHOME "pwsh.exe" }
    $options = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File")
    Assert-EngineStopped
    Write-Host "Building Gufo. The first build also compiles dependencies; this can take a while..." -ForegroundColor Cyan
    Invoke-SetupCommand $shell ($options + @("$PSScriptRoot\build.ps1", "-GufoPath", $engineRoot, "-VisualStudio", $tools.VS, "-Python", $tools.Python, "-Jobs", "$Jobs", "-Rocm", $tools.Rocm, "-Vcpkg", $tools.Vcpkg, "-Ninja", $tools.Ninja))
    $engine = Join-Path $engineRoot "build\windows-release\gufo.exe"
    Write-Host "Checking the built executable and GPU (no model is loaded)..." -ForegroundColor Cyan
    Invoke-SetupCommand $engine @("--version")
    # Run outside the build script's compiler environment, just as the GUI will.
    Invoke-SetupCommand $engine @("diagnose", "--section", "gpu")
    Invoke-SetupCommand $shell ($options + @("$PSScriptRoot\gui.ps1", "-Python", $tools.Python, "-PrepareOnly"))
    Write-Host "`nSetup complete. Next time, double-click launch-gui.bat." -ForegroundColor Green
    Write-Host "Select your model files in the GUI and save. Existing saved executable selections are unchanged; new settings default to $engine."
  } catch {
    Write-Host "Setup failed: $($_.Exception.Message)" -ForegroundColor Red
    throw
  } finally { Stop-Transcript | Out-Null }
  if (-not $NoLaunch) { Invoke-SetupCommand $shell ($options + @("$PSScriptRoot\gui.ps1")) }
}

if ($MyInvocation.InvocationName -ne ".") {
  try { Invoke-WindowsSetup } catch {
    Write-Host "`nSetup stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Completed downloads/build steps can be reused. Fix the issue and rerun setup-windows.bat. Logs: $root\build\setup-*.log"
    exit 1
  }
}
