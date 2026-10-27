"""Exercise Linux setup/update with real temporary Git repos and simulated builds."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Linux scripts require bash on POSIX")
class LinuxLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gufo launcher & spaces ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def run_bash(self, body, script="setup.sh"):
        test = self.root / "test.sh"
        test.write_text(
            f"source {shlex.quote(str(ROOT / 'tools/linux' / script))}\n"
            f"root={shlex.quote(str(self.root))}\n"
            "engine_root=\"$root/official & engine\"\n"
            "engine=\"$engine_root/build/release/gufo\"\n"
            "state_file=\"$root/build/linux-setup.json\"\n"
            "fail() { printf 'ASSERTION: %s\\n' \"$*\" >&2; exit 99; }\n"
            "reject() {  # reject PATTERN COMMAND...\n"
            "  local pattern=$1 output; shift\n"
            "  output=$( (\"$@\") 2>&1 ) && fail \"Expected rejection: $*\"\n"
            "  [[ $output == $pattern ]] || fail \"Unexpected message: $output\"\n"
            "}\n" + body,
            encoding="utf-8",
        )
        result = subprocess.run(["bash", str(test)], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_source_guard_accepts_upstream_and_rejects_fork_dirty_detached_and_wrong_branch(self):
        self.run_bash(r'''
commit() { git -C "$engine_root" -c user.name=Test -c user.email=test@example.com commit -q "$@"; }
git init -q -b main "$engine_root"
commit --allow-empty -m initial
git -C "$engine_root" remote add origin "$repository"
assert_gufo_source git
git -C "$engine_root" remote set-url origin https://github.com/thomas9120/gufo-windows.git
reject '*not official*' assert_gufo_source git
git -C "$engine_root" remote set-url origin "$repository"
printf 'keep this file\n' >"$engine_root/local.txt"
reject '*local changes*' assert_gufo_source git
[[ $(cat "$engine_root/local.txt") == 'keep this file' ]] || fail 'Local file was changed'
git -C "$engine_root" add local.txt
commit -m local
git -C "$engine_root" checkout -q -b other
reject '*Check out main*' assert_gufo_source git
git -C "$engine_root" checkout -q --detach
reject '*Check out main*' assert_gufo_source git
''')

    def test_clone_uses_official_main_and_preserves_existing_folders(self):
        self.run_bash(r'''
calls=()
setup_command() { calls+=("$*"); }
assert_gufo_source() { :; }
initialize_gufo_source git
[[ ${calls[0]} == "git clone --branch main --single-branch $repository $engine_root" ]] || fail "Wrong clone: ${calls[0]}"
mkdir -p "$engine_root/.git"
calls=()
initialize_gufo_source git
(( ${#calls[@]} == 0 )) || fail 'Existing source was cloned over'
''')

    def test_preview_changes_nothing_and_setup_orders_clone_before_build(self):
        self.run_bash(r'''
events=()
resolve_engine_root() { :; }
assert_setup_machine() { :; }
assert_setup_space() { :; }
assert_engine_stopped() { :; }
detect_setup_tools() {
  git_bin=/tools/git cmake_bin=/tools/cmake ninja_bin=/tools/ninja cxx_bin=/tools/c++
  pkg_config_bin=/tools/pkg-config python_bin=$(command -v python3) rocm_path=/opt/rocm missing_system=()
}
install_system_packages() { fail 'Unexpected installation'; }
initialize_gufo_source() { events+=(clone); }
build_gufo() { events+=("build $engine_root"); }
setup_command() { events+=("$*"); }
run_linux_setup --check-only
(( ${#events[@]} == 0 )) || fail "Preview ran: ${events[*]}"
[[ ! -e $state_file ]] || fail 'Preview wrote setup state'
run_linux_setup --yes --no-launch >/dev/null
[[ ${events[0]} == clone && ${events[1]} == "build $engine_root" ]] || fail "Wrong order: ${events[*]}"
[[ ${events[3]} == "$engine diagnose --section gpu" ]] || fail 'GPU was not checked'
[[ ${events[4]} == *"gui.sh --python"*"--prepare-only" ]] || fail 'GUI was not prepared'
[[ $(saved_value GufoPath) == "$engine_root" ]] || fail 'Custom source path not saved'
''')

    def test_setup_stops_before_changes_without_rocm(self):
        self.run_bash(r'''
assert_setup_machine() { :; }
assert_setup_space() { :; }
detect_setup_tools() { git_bin=/tools/git rocm_path="" missing_system=(); }
initialize_gufo_source() { fail 'Cloned without ROCm'; }
reject '*ROCm development files were not found*' run_linux_setup --yes --no-launch --gufo-path "$engine_root"
[[ ! -e $state_file ]] || fail 'State was written without ROCm'
''')

    def test_update_fast_forwards_only_engine_and_stops_before_build_on_pull_failure(self):
        self.run_bash(r'''
events=()
resolve_engine_root() { :; }
detect_setup_tools() {
  git_bin=/tools/git cmake_bin=/tools/cmake ninja_bin=/tools/ninja python_bin=$(command -v python3)
  rocm_path=/opt/rocm missing_system=()
}
assert_engine_stopped() { :; }
assert_gufo_source() { :; }
build_gufo() { events+=("build $engine_root"); }
setup_command() { events+=("$*"); }
run_linux_update >/dev/null
[[ ${events[0]} == "/tools/git -C $engine_root pull --ff-only --no-rebase --no-autostash $repository main" ]] ||
  fail "Updater pulled the wrong source: ${events[0]}"
[[ ${events[1]} == "build $engine_root" ]] || fail 'Updater rebuilt the wrong source'
setup_command() { die 'simulated pull failure'; }
build_gufo() { fail 'Build continued after failed pull'; }
reject '*pull failure*' run_linux_update
detect_setup_tools() { git_bin=/tools/git rocm_path="" missing_system=(); }
reject '*prerequisites are missing (ROCm*setup-linux.sh*' run_linux_update
''', script="update.sh")

    def test_build_passes_release_preset_and_rocm_and_propagates_failure(self):
        tools = self.root / "tools & spaces"
        rocm = self.root / "rocm prefix"
        (rocm / "llvm/bin").mkdir(parents=True)
        compiler = rocm / "llvm/bin/clang++"
        compiler.write_text("#!/bin/sh\n")
        compiler.chmod(0o755)
        tools.mkdir()
        log = tools / "calls.jsonl"
        cmake = tools / "cmake"
        cmake.write_text("#!/usr/bin/env python3\nimport json, os, sys\nfrom pathlib import Path\n"
                         f"with open({str(log)!r}, 'a') as f: f.write(json.dumps([os.getcwd()] + sys.argv[1:]) + '\\n')\n"
                         "if '--build' in sys.argv:\n"
                         "    Path('build/release').mkdir(parents=True, exist_ok=True)\n"
                         "    Path('build/release/gufo').touch(mode=0o755)\n"
                         "sys.exit(int(os.environ.get('TEST_FAIL', '0')))\n", encoding="utf-8")
        cmake.chmod(0o755)
        body = (f"cmake_bin={shlex.quote(str(cmake))} ninja_bin=/tools/ninja rocm_path={shlex.quote(str(rocm))} jobs=3\n"
                "mkdir -p \"$engine_root\" && printf '{}' >\"$engine_root/CMakePresets.json\"\n")
        self.run_bash(body + "build_gufo\n")
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        source = str(self.root / "official & engine")
        self.assertEqual(calls, [[source, "--preset", "release", "-DCMAKE_MAKE_PROGRAM=/tools/ninja",
                                  "-DGUFO_ENABLE_WARNINGS=OFF", f"-DCMAKE_PREFIX_PATH={rocm}",
                                  f"-DCMAKE_HIP_COMPILER={compiler}"],
                                 [source, "--build", "--preset", "release", "--target", "gufo", "--parallel", "3"]])
        log.unlink()
        self.run_bash(body + "export TEST_FAIL=7\nreject '*build failed (exit 7)*' build_gufo\n")
        self.assertEqual(len(log.read_text().splitlines()), 1, "Build ran after configure failed")

    def test_all_entrypoints_work_from_other_directory_and_forward_quoted_paths(self):
        for wrapper, script, message in (("setup-linux.sh", "setup.sh", "setup stopped"),
                                         ("update-linux.sh", "update.sh", "update stopped"),
                                         ("launch-gui.sh", "gui.sh", "launcher stopped")):
            with self.subTest(wrapper=wrapper):
                checkout = self.root / wrapper
                fake = checkout / "tools/linux" / script
                fake.parent.mkdir(parents=True)
                fake.write_text('printf "VALUE=%s\\n" "$2"\nexit "${TEST_EXIT:-0}"\n')
                shutil.copy2(ROOT / wrapper, checkout / wrapper)
                selected = str(self.root / "selected & path")
                result = subprocess.run([str(checkout / wrapper), "--option", selected], cwd=self.root,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"VALUE={selected}", result.stdout)
                result = subprocess.run([str(checkout / wrapper)], cwd=self.root, env=os.environ | {"TEST_EXIT": "5"},
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 5)
                self.assertIn(message, result.stdout)


if __name__ == "__main__":
    unittest.main()
