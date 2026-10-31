"""Installer contracts: plans are read-only, execution is reviewed, and children are owned."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/installer"))
from core import (GUI_REPOSITORY, REPOSITORY, Installer, Options, Runner,
                  load_options, operation_lock, parse_event, save_options)
from main import main


class InstallerTest(unittest.TestCase):
    def test_commands_preserve_argument_boundaries_and_disable_launch(self):
        options = Options(str(ROOT / "engine & space"), str(ROOT / "rock & space"), jobs=6)
        for windows in (True, False):
            installer = Installer(windows=windows)
            command = installer.command("install", options)
            self.assertIn(options.gufo_path, command)
            self.assertIn(options.rocm, command)
            self.assertIn("-NoLaunch" if windows else "--no-launch", command)
            plan = installer.command("update", options, Path("plan & space.json"))
            self.assertIn("-CheckOnly" if windows else "--check-only", plan)
            self.assertIn("plan & space.json", plan)
            self.assertNotIn("-Yes", plan)
        for options in (Options(jobs=0), Options(jobs=65), Options(gufo_path=str(ROOT)), Options(rocm="bad\npath")):
            with self.assertRaises(ValueError):
                options.validate()

    def test_options_and_setup_state_do_not_touch_presets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build").mkdir()
            (root / "build/windows-setup.json").write_text(json.dumps({"GufoPath": str(root / "official")}))
            self.assertEqual(load_options(root, windows=True).gufo_path, str(root / "official"))
            options = Options(str(root / "custom"), jobs=8)
            save_options(options, root)
            self.assertEqual(load_options(root, windows=True), options)
            self.assertEqual({p.name for p in (root / "build").iterdir()}, {"windows-setup.json", "installer-options.json"})

    def test_events_are_structured_and_malformed_lines_remain_logs(self):
        self.assertEqual(parse_event('GUFO_EVENT {"schema":1,"phase":"build"}')["phase"], "build")
        for line in ('GUFO_EVENT {}', 'GUFO_EVENT []', 'GUFO_EVENT {"schema":1,"phase":[]}', 'GUFO_EVENT garbage', 'Compiling engine',
                     'GUFO_EVENT {"schema":1,"phase":"unknown"}'):
            self.assertIsNone(parse_event(line))

    def test_runner_streams_utf8_and_preserves_nonzero_status(self):
        with tempfile.TemporaryDirectory() as directory:
            lines = []
            log = Path(directory) / "result.log"
            code = Runner().run([sys.executable, "-u", "-c", "print('café'); raise SystemExit(7)"],
                                ROOT, lines.append, log)
            self.assertEqual(code, 7)
            self.assertEqual(lines, ["café"])
            self.assertEqual(log.read_text(encoding="utf-8"), "café\n")

    def test_cancellation_kills_descendant_before_it_can_write(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "must-not-exist"
            child = f"import pathlib,time; time.sleep(2); pathlib.Path({str(marker)!r}).touch()"
            script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); print('ready',flush=True); time.sleep(30)"
            runner = Runner()
            ready = threading.Event()
            result = []
            worker = threading.Thread(target=lambda: result.append(runner.run(
                [sys.executable, "-u", "-c", script, child], ROOT, lambda line: ready.set())))
            worker.start()
            try:
                self.assertTrue(ready.wait(5), "Child never started")
                runner.cancel()
                worker.join(5)
                self.assertFalse(worker.is_alive(), "Cancellation left runner blocked")
                self.assertEqual(result, [2])
                time.sleep(2.1)
                self.assertFalse(marker.exists(), "Descendant survived cancellation")
            finally:
                runner.cancel()
                worker.join(5)

    def test_lock_rejects_second_process_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from core import operation_lock\nwith operation_lock(Path(sys.argv[2])): print('acquired')"
            command = [sys.executable, "-c", script, str(ROOT / "tools/installer"), directory]
            with operation_lock(root):
                result = subprocess.run(command, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Another Gufo installer", result.stderr)
            self.assertEqual(subprocess.run(command, capture_output=True, timeout=5).returncode, 0)

    def test_plain_check_only_never_executes(self):
        plan = dict(schema=1, repository=REPOSITORY, gufoPath="official", jobs=4)
        with patch.object(sys, "argv", ["main.py", "--plain", "--action", "install", "--check-only"]), \
             patch("main.Installer.plan", return_value=plan), patch("main.Installer.execute") as execute:
            self.assertEqual(main(), 0)
            execute.assert_not_called()

    def test_gui_update_fast_forwards_and_rejects_dirty_or_divergent_history(self):
        with tempfile.TemporaryDirectory() as directory:
            upstream = Path(directory) / "upstream"
            checkout = Path(directory) / "gui & spaces"

            def git(path, *args):
                return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout.strip()

            upstream.mkdir()
            git(upstream, "init", "-b", "main")
            for key, value in (("user.name", "Test"), ("user.email", "test@example.com")):
                git(upstream, "config", key, value)
            (upstream / ".gitignore").write_text("/build/\n")
            git(upstream, "add", ".gitignore")
            git(upstream, "commit", "-m", "initial")
            subprocess.run(["git", "clone", str(upstream), str(checkout)], check=True, capture_output=True)
            git(checkout, "remote", "set-url", "origin", GUI_REPOSITORY)
            git(checkout, "config", f"url.{upstream.as_posix()}.insteadOf", GUI_REPOSITORY)
            # build is ignored in the real GUI repository.
            (upstream / "README.md").write_text("updated")
            git(upstream, "add", "README.md")
            git(upstream, "commit", "-m", "update")
            installer = Installer(checkout)
            installer.update_gui(lambda line: None)
            self.assertEqual(git(checkout, "rev-parse", "HEAD"), git(upstream, "rev-parse", "HEAD"))
            (checkout / "keep.txt").write_text("local")
            with self.assertRaisesRegex(RuntimeError, "local changes"):
                installer.update_gui(lambda line: None)
            self.assertEqual((checkout / "keep.txt").read_text(), "local")
            for key, value in (("user.name", "Test"), ("user.email", "test@example.com")):
                git(checkout, "config", key, value)
            git(checkout, "add", "keep.txt")
            git(checkout, "commit", "-m", "local")
            before = git(checkout, "rev-parse", "HEAD")
            git(upstream, "commit", "--allow-empty", "-m", "diverge")
            with self.assertRaisesRegex(RuntimeError, "update failed"):
                installer.update_gui(lambda line: None)
            self.assertEqual(git(checkout, "rev-parse", "HEAD"), before)


try:
    from tui import SetupApp
    from textual.widgets import Button, Input
except ImportError:
    SetupApp = None


@unittest.skipUnless(SetupApp, "Install tools/installer/requirements.txt for headless TUI checks")
class TuiTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_requires_confirmation_and_returns_to_menu(self):
        class FakeInstaller(Installer):
            def execute(self, action, options, runner, on_line):
                runner.cancelled.wait(10)
                return 2

        with tempfile.TemporaryDirectory() as directory:
            app = SetupApp(FakeInstaller(Path(directory)), Options())
            async with app.run_test(size=(100, 32)) as pilot:
                app.selected_action = "install"
                app.start_activity("Installing")
                app.perform()
                await pilot.pause()
                self.assertTrue(await pilot.click("#cancel"))
                await pilot.click("#no")
                self.assertTrue(app.busy)
                self.assertFalse(app.runner.cancelled.is_set())
                await pilot.click("#cancel")
                await pilot.click("#yes")
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertFalse(app.busy)
                self.assertFalse(app.quit_pending, "Cancel button unexpectedly quit the app")
                await pilot.click("#activity-back")
                self.assertEqual(app.view, "home")

    async def test_keyboard_navigation_plan_review_and_execution(self):
        class FakeInstaller(Installer):
            executions = 0

            def plan(self, action, options, runner, on_line):
                return dict(schema=1, repository=REPOSITORY, gufoPath="official", jobs=4)

            def execute(self, action, options, runner, on_line):
                self.executions += 1
                on_line('GUFO_EVENT {"schema":1,"phase":"build"}')
                on_line("Compiler output")
                return 0

        with tempfile.TemporaryDirectory() as directory:
            installer = FakeInstaller(Path(directory))
            app = SetupApp(installer, Options())
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.press("enter")
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertEqual(app.view, "review")
                self.assertEqual(installer.executions, 0, "Inspection ran installation")
                # Back is focused, so Enter cannot accidentally accept the plan.
                await pilot.press("enter")
                self.assertEqual(app.view, "home")
                await pilot.press("enter")
                await app.workers.wait_for_complete()
                await pilot.pause()
                await pilot.click("#execute")
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertEqual(installer.executions, 1)
                self.assertFalse(app.busy)
                self.assertFalse(app.query_one("#activity-back", Button).disabled)
                self.assertIn("build", app.completed_phases)
                await pilot.press("escape", "f2")
                app.query_one("#jobs", Input).value = "0"
                await pilot.click("#save")
                self.assertEqual(app.view, "settings")
                self.assertEqual(app.options.jobs, 4)

    async def test_small_terminal_remains_navigable(self):
        app = SetupApp()
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.press("down", "down", "down", "down", "down", "enter")
            self.assertEqual(app.view, "settings")
            await pilot.press("escape")
            self.assertEqual(app.view, "home")
