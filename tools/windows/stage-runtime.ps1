# Run inside the selected Visual Studio environment, after upstream stages HIP.
param([Parameter(Mandatory)][string]$BuildPath)
$ErrorActionPreference = "Stop"
$dependencies = Join-Path $BuildPath "vcpkg_installed\x64-windows-release\bin"
Get-ChildItem -LiteralPath $dependencies -Filter "*.dll" | Copy-Item -Destination $BuildPath -Force
if ($env:VCToolsRedistDir) {
  Get-ChildItem "$env:VCToolsRedistDir/x64/Microsoft.VC*.CRT/*.dll" | Copy-Item -Destination $BuildPath -Force
}
# Match the import library selected by CMake, including VS's dotted DLL name.
$openmp = Select-String -LiteralPath (Join-Path $BuildPath "CMakeCache.txt") -Pattern '^OpenMP_libomp_LIBRARY:FILEPATH=(.*)$'
if ($openmp -and $openmp.Matches[0].Groups[1].Value -notmatch '-NOTFOUND$') {
  $library = $openmp.Matches[0].Groups[1].Value.Replace('\', '/')
  if ($library -match '^(.*)/VC/Tools/MSVC/([^/]+)/lib/x64/libomp\.lib$') {
    $redist = "$($Matches[1])/VC/Redist/MSVC/$($Matches[2])"
    if ($env:VCToolsRedistDir -and $env:VCToolsRedistDir.Replace('\', '/').StartsWith(
        "$($Matches[1])/VC/Redist/MSVC/", [StringComparison]::OrdinalIgnoreCase)) {
      $redist = $env:VCToolsRedistDir
    }
    $runtime = Get-ChildItem "$redist/debug_nonredist/x64/Microsoft.VC*.OpenMP.LLVM/libomp140.x86_64.dll" -ErrorAction SilentlyContinue
    if (-not $runtime) { throw "Cannot find this build's local OpenMP runtime under $redist." }
    $runtime | Copy-Item -Destination $BuildPath -Force
  } else {
    $runtime = [IO.Path]::GetFullPath((Join-Path (Split-Path $library) "..\bin\libomp.dll"))
    if (-not (Test-Path -LiteralPath $runtime)) { throw "Cannot find the OpenMP runtime for $library." }
    Copy-Item -LiteralPath $runtime -Destination $BuildPath -Force
  }
}
