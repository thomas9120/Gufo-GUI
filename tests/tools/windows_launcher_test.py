"""Exercise setup/update with real temporary Git repos and simulated builds."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == "nt", "Windows scripts require Windows")
class WindowsLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gufo launcher & spaces ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.environment = {key: value for key, value in os.environ.items() if key.lower() != "psmodulepath"}

    def run_ps(self, body):
        for index, name in enumerate(("powershell.exe", "pwsh.exe")):
            shell = shutil.which(name)
            if not shell:
                continue
            with self.subTest(shell=name):
                case = self.root / str(index)
                case.mkdir()
                script = case / "test.ps1"
                script.write_text(
                    f". {quote(ROOT / 'tools/windows/setup.ps1')}\n"
                    f"$root = {quote(case)}\n"
                    "$engineRoot = Join-Path $root 'official & engine'\n"
                    "$stateFile = Join-Path $root 'build/windows-setup.json'\n"
                    "$deps = Join-Path $root 'dependencies'\n"
                    "$ErrorActionPreference = 'Stop'\n"
                    "function Assert($ok, $message) { if (-not $ok) { throw $message } }\n"
                    "function Reject($action, $message) {\n"
                    "  try { & $action } catch { Assert ($_.Exception.Message -like $message) $_; return }; throw 'Expected rejection'\n"
                    "}\n" + body,
                    encoding="utf-8-sig",
                )
                result = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                        cwd=self.root, env=self.environment, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_source_guard_accepts_upstream_and_rejects_fork_dirty_detached_and_wrong_branch(self):
        self.run_ps(r'''
$git = (Get-Command git.exe).Source
Invoke-SetupCommand $git @('init', '-b', 'main', $engineRoot)
Invoke-SetupCommand $git @('-C', $engineRoot, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '--allow-empty', '-m', 'initial')
Invoke-SetupCommand $git @('-C', $engineRoot, 'remote', 'add', 'origin', $repository)
Assert-GufoSource $git
Invoke-SetupCommand $git @('-C', $engineRoot, 'remote', 'set-url', 'origin', 'https://github.com/thomas9120/gufo-windows.git')
Reject { Assert-GufoSource $git } '*not official*'
Invoke-SetupCommand $git @('-C', $engineRoot, 'remote', 'set-url', 'origin', $repository)
Set-Content -LiteralPath (Join-Path $engineRoot 'local.txt') -Value 'keep this file'
Reject { Assert-GufoSource $git } '*local changes*'
Assert ((Get-Content -LiteralPath (Join-Path $engineRoot 'local.txt')) -eq 'keep this file') 'Local file was changed'
Invoke-SetupCommand $git @('-C', $engineRoot, 'add', 'local.txt')
Invoke-SetupCommand $git @('-C', $engineRoot, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'local')
Invoke-SetupCommand $git @('-C', $engineRoot, 'checkout', '-b', 'other')
Reject { Assert-GufoSource $git } '*Check out main*'
Invoke-SetupCommand $git @('-C', $engineRoot, 'checkout', '--detach')
Reject { Assert-GufoSource $git } '*Check out main*'
''')

    def test_clone_uses_official_main_and_preserves_existing_folders(self):
        self.run_ps(r'''
$calls = [Collections.Generic.List[object]]::new()
function Invoke-SetupCommand($File, $Arguments) { $calls.Add(@($Arguments)) }
function Assert-GufoSource { }
Initialize-GufoSource 'git.exe'
Assert (($calls[0] -join '|') -eq "clone|--branch|main|--single-branch|$repository|$engineRoot") 'Wrong clone source'
New-Item -ItemType Directory -Path (Join-Path $engineRoot '.git') -Force | Out-Null
$calls.Clear()
Initialize-GufoSource 'git.exe'
Assert ($calls.Count -eq 0) 'Existing source was cloned over'
''')

    def test_preview_no_changes_and_setup_orders_clone_before_manifest_and_build(self):
        self.run_ps(r'''
$Yes = $true; $NoLaunch = $true
$events = [Collections.Generic.List[string]]::new()
function Assert-SetupMachine { }
function Assert-SetupSpace { }
function Assert-EngineStopped { }
function Get-SetupTools {
  [pscustomobject]@{Git='C:\tools\git.exe'; VS='C:\vs'; CMake='C:\tools\cmake.exe';
    Ninja='C:\tools\ninja.exe'; Python='C:\python\python.exe'; Rocm='C:\rock'; Vcpkg='C:\vcpkg'; GufoPath=$engineRoot}
}
function Initialize-GufoSource { $events.Add('clone') }
function Initialize-SetupVcpkg { $events.Add('vcpkg'); return 'C:\vcpkg' }
function Invoke-SetupCommand($File, $Arguments) { $events.Add("$File $Arguments") }
function Install-SetupPackage { throw 'Unexpected installation' }
function Install-SetupRock { throw 'Unexpected download' }
$CheckOnly = $true
$PlanJson = Join-Path $root 'plan.json'
function Get-CimInstance { [pscustomobject]@{Name='Test'; Caption='Test'; BuildNumber=22000; TotalVisibleMemorySize=1GB} }
Invoke-WindowsSetup
Assert ($events.Count -eq 0) 'Preview ran a command'
Assert (-not (Test-Path -LiteralPath $stateFile)) 'Preview wrote setup state'
$plan = Get-Content -LiteralPath $PlanJson -Raw | ConvertFrom-Json
Assert ($plan.repository -eq $repository -and $plan.gufoPath -eq $engineRoot) 'Plan omitted official source'
$CheckOnly = $false
Invoke-WindowsSetup
Assert ($events[0] -eq 'clone' -and $events[1] -eq 'vcpkg') 'Manifest read before clone'
$build = @($events | Where-Object { $_ -like '*build.ps1*' })
Assert ($build.Count -eq 1 -and $build[0].Contains("-GufoPath $engineRoot")) 'Build missed engine path'
Assert (@($events | Where-Object { $_ -like '*windows-release\gufo.exe diagnose*' }).Count -eq 1) 'GPU was not checked'
$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
Assert ($state.GufoPath -eq $engineRoot) 'Custom source path not saved'
''')

    def test_update_fast_forwards_only_engine_and_stops_before_build_on_pull_failure(self):
        self.run_ps(f". {quote(ROOT / 'tools/windows/update.ps1')}\n" + r'''
$root = Split-Path -Parent $PSCommandPath
$engineRoot = Join-Path $root 'official & engine'
$stateFile = Join-Path $root 'build/windows-setup.json'
New-Item -ItemType Directory -Path (Split-Path $stateFile) -Force | Out-Null
$vcpkgPath = Join-Path $root 'vcpkg'
New-Item -ItemType Directory -Path $vcpkgPath | Out-Null
Set-Content -LiteralPath (Join-Path $vcpkgPath 'vcpkg.exe') -Value 'fixture'
$events = [Collections.Generic.List[object]]::new()
function Get-SetupTools {
  [pscustomobject]@{Git='C:\tools\git.exe'; VS='C:\vs'; CMake='C:\tools\cmake.exe';
    Ninja='C:\tools\ninja.exe'; Python='C:\python\python.exe'; Rocm='C:\rock'; Vcpkg=$vcpkgPath; GufoPath=$engineRoot}
}
function Assert-EngineStopped { }
function Assert-GufoSource { }
function Initialize-SetupVcpkg { return $vcpkgPath }
function Invoke-SetupCommand($File, $Arguments) { $events.Add(@($Arguments)) }
Invoke-WindowsUpdate
Assert (($events[0] -join '|') -eq "-C|$engineRoot|pull|--ff-only|--no-rebase|--no-autostash|$repository|main") 'Updater pulled the wrong source'
Assert (($events[1] -join '|').Contains("-GufoPath|$engineRoot")) 'Updater rebuilt the wrong source'
$events.Clear()
function Invoke-SetupCommand { throw 'simulated pull failure' }
Reject { Invoke-WindowsUpdate } '*pull failure*'
Assert ($events.Count -eq 0) 'Build continued after failed pull'
''')

    def test_build_batch_preserves_quoted_tool_paths_and_propagates_failure(self):
        tools = self.root / "tools & spaces"
        tools.mkdir()
        recorder = tools / "record.py"
        log = tools / "calls.jsonl"
        recorder.write_text("import json, os, sys\nfrom pathlib import Path\n"
                            "assert os.environ['HIP_PATH'] == 'selected HIP'\n"
                            "assert os.environ['VCPKG_ROOT'] == 'selected vcpkg'\n"
                            "with Path(os.environ['TEST_LOG']).open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                            "sys.exit(int(os.environ.get('TEST_FAIL', '0')))\n", encoding="utf-8")
        vcvars = tools / "vcvars64.bat"
        vcvars.write_text('@echo off\nset "VCPKG_ROOT=wrong"\nset "HIP_PATH=wrong"\nexit /b 0\n')
        cmake = tools / "cmake.cmd"
        cmake.write_text(f'@echo off\n"{sys.executable}" "{recorder}" %*\nexit /b %errorlevel%\n')
        shell = tools / "fake powershell.cmd"
        shell.write_text('@echo off\nexit /b 0\n')
        environment = self.environment | {"GUFO_VCVARS": str(vcvars), "GUFO_CMAKE": str(cmake),
                                          "GUFO_NINJA": str(tools / "ninja.exe"), "GUFO_BUILD_JOBS": "3", "TEST_LOG": str(log),
                                          "HIP_PATH": "selected HIP", "VCPKG_ROOT": "selected vcpkg"}
        environment.update(GUFO_POWERSHELL=str(shell), GUFO_BUILD_DIR=str(tools))
        def run():
            return subprocess.run([os.environ["COMSPEC"], "/d", "/c", str(ROOT / "tools/windows/build-upstream.cmd")],
                                  env=environment, cwd=self.root, capture_output=True, text=True, timeout=30)
        result = run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(calls, [["--preset", "windows-release",
                                 "-DCMAKE_MAKE_PROGRAM=" + environment["GUFO_NINJA"], "-DGUFO_ENABLE_WARNINGS=OFF"],
                                ["--build", "--preset", "windows-release", "--target", "gufo", "--parallel", "3"]])
        environment["TEST_FAIL"] = "7"
        self.assertEqual(run().returncode, 7)
        self.assertEqual(len(log.read_text().splitlines()), 3, "Build ran after configure failed")

    def test_reused_vcpkg_fetches_a_new_manifest_baseline(self):
        self.run_ps(r'''
$git = (Get-Command git.exe).Source
$vcpkgPath = Join-Path $root 'vcpkg'
Invoke-SetupCommand $git @('init', '-b', 'main', $vcpkgPath)
New-Item -ItemType Directory -Path $engineRoot | Out-Null
$revision = '0123456789012345678901234567890123456789'
Set-Content -LiteralPath (Join-Path $engineRoot 'vcpkg.json') -Value ('{"builtin-baseline":"' + $revision + '"}')
Set-Content -LiteralPath (Join-Path $vcpkgPath 'vcpkg.exe') -Value 'fixture'
$calls = [Collections.Generic.List[object]]::new()
function Invoke-SetupCommand($File, $Arguments) { $calls.Add(@($Arguments)) }
$found = Initialize-SetupVcpkg $git $vcpkgPath
Assert ($found -eq $vcpkgPath) 'Reused vcpkg path changed'
Assert ($calls.Count -eq 1 -and ($calls[0] -join '|') -eq "-C|$vcpkgPath|fetch|origin|$revision") 'New baseline was not fetched'
''')

    def test_build_wrapper_selects_one_cmake_when_multiple_are_on_path(self):
        source = self.root / "upstream & source"
        scripts = source / "tools/windows"
        scripts.mkdir(parents=True)
        (source / "CMakePresets.json").write_text('{}')
        patch_log = source / "patch-path.txt"
        (scripts / "patch_sdk_math.py").write_text(
            "import os, sys\nfrom pathlib import Path\n"
            "assert os.environ['ROCM_PATH'] == sys.argv[1]\n"
            "assert os.environ['HIP_DEVICE_LIB_PATH'] == sys.argv[1] + '/lib/llvm/amdgcn/bitcode'\n"
            f"Path({str(patch_log)!r}).write_text(sys.argv[1])\n", encoding="utf-8")
        recorder = source / "record.py"
        recorder.write_text("import json, sys\nfrom pathlib import Path\n"
                            "with Path('calls.jsonl').open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                            "Path('build/windows-release').mkdir(parents=True, exist_ok=True)\n"
                            "Path('build/windows-release/gufo.exe').touch()\n", encoding="utf-8")
        dependencies = source / "build/windows-release/vcpkg_installed/x64-windows-release/bin"
        dependencies.mkdir(parents=True)
        (dependencies / "test.dll").write_bytes(b"runtime")
        (source / "build/windows-release/CMakeCache.txt").write_text('')
        vcvars = source / "VC/Auxiliary/Build/vcvars64.bat"
        vcvars.parent.mkdir(parents=True)
        vcvars.write_text('@echo off\nset "VCToolsRedistDir="\nexit /b 0\n')
        cmake = source / "cmake.cmd"
        cmake.write_text(f'@echo off\n"{sys.executable}" "{recorder}" %*\nexit /b %errorlevel%\n')
        self.run_ps(
            "function Get-Command { param($Name, $CommandType, $ErrorAction)\n"
            f"  if ($Name -eq 'cmake.exe') {{ [pscustomobject]@{{Source={quote(cmake)}}}; [pscustomobject]@{{Source='wrong second cmake'}} }}\n"
            "  else { [pscustomobject]@{Source=$Name} }\n}\n"
            f"& {quote(ROOT / 'tools/windows/build.ps1')} -GufoPath {quote(source)} "
            f"-VisualStudio {quote(source)} "
            f"-Rocm {quote(self.root)} -Vcpkg {quote(self.root)} -Ninja {quote(sys.executable)} -Python {quote(sys.executable)}\n"
            "Assert ($LASTEXITCODE -eq 0) 'Build wrapper failed'\n")
        calls = [json.loads(line) for line in (source / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(calls[0][:2], ["--preset", "windows-release"])
        self.assertEqual(Path(patch_log.read_text()), self.root)
        self.assertNotIn('\\', patch_log.read_text())
        self.assertEqual((source / "build/windows-release/test.dll").read_bytes(), b"runtime")

    def test_runtime_staging_matches_selected_visual_studio_openmp(self):
        self.run_ps(f"$stage = {quote(ROOT / 'tools/windows/stage-runtime.ps1')}\n" + r'''
$build = Join-Path $root 'engine build'
$dependencies = Join-Path $build 'vcpkg_installed/x64-windows-release/bin'
New-Item -ItemType Directory -Path $dependencies -Force | Out-Null
Set-Content -LiteralPath (Join-Path $dependencies 'icu.dll') -Value 'icu runtime'
$vs = Join-Path $root 'VS'
$env:VCToolsRedistDir = Join-Path $vs 'VC/Redist/MSVC/14.51.1'
$crt = Join-Path $env:VCToolsRedistDir 'x64/Microsoft.VC145.CRT'
$omp = Join-Path $env:VCToolsRedistDir 'debug_nonredist/x64/Microsoft.VC145.OpenMP.LLVM'
New-Item -ItemType Directory -Path $crt, $omp -Force | Out-Null
Set-Content -LiteralPath (Join-Path $crt 'msvcp140.dll') -Value 'CRT runtime'
Set-Content -LiteralPath (Join-Path $omp 'libomp140.x86_64.dll') -Value 'matching OpenMP runtime'
$library = (Join-Path $vs 'VC/Tools/MSVC/14.51.2/lib/x64/libomp.lib').Replace('\', '/')
Set-Content -LiteralPath (Join-Path $build 'CMakeCache.txt') -Value "OpenMP_libomp_LIBRARY:FILEPATH=$library"
& $stage -BuildPath $build
Assert ((Get-Content -LiteralPath (Join-Path $build 'icu.dll')) -eq 'icu runtime') 'vcpkg DLL missing'
Assert ((Get-Content -LiteralPath (Join-Path $build 'msvcp140.dll')) -eq 'CRT runtime') 'CRT missing'
Assert ((Get-Content -LiteralPath (Join-Path $build 'libomp140.x86_64.dll')) -eq 'matching OpenMP runtime') 'Wrong OpenMP DLL'
''')

    def test_all_entrypoints_work_from_other_directory_and_forward_quoted_paths(self):
        for batch_name, script_name, option in (("setup-windows.bat", "setup.ps1", "GufoPath"),
                                                 ("update-windows.bat", "update.ps1", "GufoPath"),
                                                 ("launch-gui.bat", "gui.ps1", "Config")):
            with self.subTest(batch=batch_name):
                checkout = self.root / batch_name
                script = checkout / "tools/windows" / script_name
                script.parent.mkdir(parents=True)
                script.write_text(f'param([string]${option})\nWrite-Output "VALUE=${option}"\nexit 0\n')
                batch = checkout / batch_name
                shutil.copy2(ROOT / batch_name, batch)
                selected = self.root / "selected & path"
                command = f'"{os.environ["COMSPEC"]}" /d /s /c ""{batch}" -{option} "{selected}""'
                result = subprocess.run(command, cwd=self.root, env=self.environment,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"VALUE={selected}", result.stdout)
