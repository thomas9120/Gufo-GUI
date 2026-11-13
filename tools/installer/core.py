"""Installer operations shared by the TUI and plain CLI. No Textual dependency."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "https://github.com/gufo-org/gufo.git"
GUI_REPOSITORY = "https://github.com/thomas9120/Gufo-GUI.git"
EVENT_PREFIX = "GUFO_EVENT "
PHASES = {"inspect": "Inspect machine and tools", "tools": "Prepare build tools",
          "source": "Prepare official Gufo source", "dependencies": "Prepare libraries and GPU runtime",
          "build": "Compile engine", "verify": "Verify executable and GPU",
          "gui": "Prepare GUI environment", "complete": "Finish"}


@dataclass
class Options:
    gufo_path: str = ""
    rocm: str = ""
    vcpkg: str = ""
    jobs: int = 4

    def validate(self, root=ROOT):
        if type(self.jobs) is not int or not 1 <= self.jobs <= 64:
            raise ValueError("Build jobs must be a whole number from 1 to 64.")
        for name in ("gufo_path", "rocm", "vcpkg"):
            value = getattr(self, name)
            if not isinstance(value, str) or any(ord(c) < 32 for c in value):
                raise ValueError(f"{name}: enter a single line path.")
        if self.gufo_path and Path(self.gufo_path).expanduser().resolve() == root.resolve():
            raise ValueError("Choose a separate folder for the Gufo engine.")
        return self


def load_options(root=ROOT, windows=None):
    windows = os.name == "nt" if windows is None else windows
    options = Options()
    state = root / "build" / ("windows-setup.json" if windows else "linux-setup.json")
    for path, keys in ((state, {"GufoPath": "gufo_path", "Rocm": "rocm", "Vcpkg": "vcpkg"}),
                       (root / "build/installer-options.json", None)):
        try:
            values = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(values, dict):
                continue
            candidate = Options(**asdict(options))
            for source, target in (keys or {key: key for key in asdict(options)}).items():
                if source in values:
                    setattr(candidate, target, values[source])
            options = candidate.validate(root)
        except (OSError, ValueError, TypeError):
            continue
    return options


def save_options(options, root=ROOT):
    options.validate(root)
    path = root / "build/installer-options.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix="installer-options-", suffix=".tmp", delete=False) as file:
        temporary = Path(file.name)
        json.dump(asdict(options), file, indent=2)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_event(line):
    if line.startswith(EVENT_PREFIX):
        try:
            event = json.loads(line[len(EVENT_PREFIX):])
            if (isinstance(event, dict) and event.get("schema") == 1
                    and isinstance(event.get("phase"), str) and event["phase"] in PHASES):
                return event
        except (ValueError, AttributeError):
            pass
    return None


class Runner:
    """One owned process tree, streamed logs, and cancellation even while output is quiet."""

    def __init__(self):
        self.cancelled = threading.Event()
        self._mutex = threading.Lock()
        self._process = None
        self._job = None

    def cancel(self):
        self.cancelled.set()
        self._stop_tree()

    def _stop_tree(self):
        with self._mutex:
            if self._job is not None:
                self._job.terminate()
            elif self._process is not None:
                if os.name == "nt":
                    self._process.kill()
                else:
                    try:
                        os.killpg(self._process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def run(self, command, cwd, on_line=lambda line: None, log=None):
        environment = os.environ | {"GUFO_INSTALLER_EVENTS": "1", "PYTHONUTF8": "1"}
        # PowerShell's inherited module path can belong to a different PS edition.
        environment = {k: v for k, v in environment.items() if k.lower() != "psmodulepath"}
        job = None
        stream = None
        try:
            if log:
                log.parent.mkdir(parents=True, exist_ok=True)
                stream = log.open("a", encoding="utf-8")
            if os.name == "nt":
                sys.path.insert(0, str(ROOT / "tools/gui"))
                from windows_job import WindowsJob
                job = WindowsJob()
                launch = [sys.executable, "-u", str(ROOT / "tools/installer/process_gate.py"), json.dumps(command)]
            else:
                launch = command
            with self._mutex:
                if self.cancelled.is_set():
                    return 2
                process = subprocess.Popen(launch, cwd=cwd, env=environment,
                                           stdin=subprocess.PIPE if job else subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           encoding="utf-8", errors="replace", bufsize=1,
                                           start_new_session=os.name != "nt")
                self._process, self._job = process, job
                if job:
                    try:
                        job.assign(process)
                        process.stdin.write("start\n")
                        process.stdin.close()
                    except BaseException:
                        process.kill()
                        process.wait()
                        raise
            try:
                for line in process.stdout:
                    line = line.rstrip("\r\n")
                    if stream:
                        stream.write(line + "\n")
                        stream.flush()
                    on_line(line)
                code = process.wait()
                return 2 if self.cancelled.is_set() else code
            finally:
                self._stop_tree()
                process.wait()
                process.stdout.close()
        finally:
            with self._mutex:
                self._process = self._job = None
                if job:
                    job.close()
            if stream:
                stream.close()


@contextmanager
def operation_lock(root):
    """OS lock releases on crashes; the persistent file needs no stale-lock deletion."""
    path = root / "build/installer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RuntimeError("Another Gufo installer is running in this folder.") from error
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RuntimeError("Another Gufo installer is running in this folder.") from error
        yield


class Installer:
    def __init__(self, root=ROOT, windows=None):
        self.root = root.resolve()
        self.windows = os.name == "nt" if windows is None else windows
        self.last_log = None

    def command(self, action, options, plan_path=None):
        options.validate(self.root)
        if action not in ("install", "repair", "update", "launch"):
            raise ValueError("Unknown installer action")
        if action == "launch":
            script = "gui"
        else:
            script = "update" if action == "update" else "setup"
        if self.windows:
            command = [shutil.which("powershell.exe") or "powershell.exe", "-NoLogo", "-NoProfile",
                       "-ExecutionPolicy", "Bypass", "-File", str(self.root / f"tools/windows/{script}.ps1")]
            if action == "launch":
                return command
            command += ["-Jobs", str(options.jobs)]
            for key, value in (("GufoPath", options.gufo_path), ("Rocm", options.rocm), ("Vcpkg", options.vcpkg)):
                if value:
                    command += [f"-{key}", str(Path(value).expanduser().resolve())]
            if plan_path:
                command += ["-CheckOnly", "-PlanJson", str(plan_path)]
            elif action != "update":
                command += ["-Yes", "-NoLaunch"]
        else:
            command = ["bash", str(self.root / f"tools/linux/{script}.sh")]
            if action == "launch":
                return command
            command += ["--jobs", str(options.jobs)]
            for key, value in (("gufo-path", options.gufo_path), ("rocm", options.rocm)):
                if value:
                    command += [f"--{key}", str(Path(value).expanduser().resolve())]
            if plan_path:
                command += ["--check-only", "--plan-json", str(plan_path)]
            elif action != "update":
                command += ["--yes", "--no-launch"]
        return command

    def plan(self, action, options, runner, on_line=lambda line: None):
        with tempfile.TemporaryDirectory(prefix="gufo-plan-") as directory:
            path = Path(directory) / "plan.json"
            code = runner.run(self.command(action, options, path), self.root, on_line)
            if code:
                raise RuntimeError("Inspection cancelled." if code == 2 else "Inspection failed. Read the log output above.")
            plan = json.loads(path.read_text(encoding="utf-8-sig"))
            if plan.get("schema") != 1 or plan.get("repository") != REPOSITORY:
                raise RuntimeError("Unsupported setup plan. Update Gufo-GUI before continuing.")
            return plan

    def execute(self, action, options, runner, on_line=lambda line: None):
        self.last_log = self.root / "build/installer-logs" / f"{action}-{datetime.now():%Y%m%d-%H%M%S-%f}.log"
        with operation_lock(self.root):
            save_options(options, self.root)
            return runner.run(self.command(action, options), self.root, on_line, self.last_log)

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Git inspection failed.")
        return result.stdout.strip()

    def gui_update_plan(self):
        if Path(self.git("rev-parse", "--show-toplevel")).resolve() != self.root:
            raise RuntimeError("GUI updates require a Git checkout. Download a new source archive instead.")
        remote = self.git("config", "--get", "remote.origin.url")
        if not re.fullmatch(r"(?:https://github\.com/|git@github\.com:)thomas9120/Gufo-GUI(?:\.git)?/?", remote, re.I):
            raise RuntimeError("GUI origin is not thomas9120/Gufo-GUI. Update this checkout manually.")
        if self.git("symbolic-ref", "--short", "HEAD") != "main":
            raise RuntimeError("GUI updates require main. This branch is kept intact; update it manually.")
        if self.git("status", "--porcelain", "--untracked-files=all"):
            raise RuntimeError("GUI checkout has local changes or untracked files. Commit, stash, or move them first.")
        return self.git("rev-parse", "--short", "HEAD")

    def update_gui(self, on_line=print):
        # Called only after Textual has exited. Git is the external update helper;
        # no Python modules or assets are loaded again until the next launch.
        with operation_lock(self.root):
            self.gui_update_plan()
            runner = Runner()
            self.last_log = self.root / "build/installer-logs" / f"update-gui-{datetime.now():%Y%m%d-%H%M%S-%f}.log"
            code = runner.run(["git", "-C", str(self.root), "pull", "--ff-only", "--no-rebase",
                               "--no-autostash", GUI_REPOSITORY, "main"], self.root, on_line, self.last_log)
            if code:
                raise RuntimeError("GUI update failed. Your local changes were not discarded.")
        on_line("GUI updated. Run Gufo Setup again to load the new version.")


def describe_plan(plan, action):
    lines = [f"{action.title()} official Gufo (main)", f"Source: {plan['repository']}",
             f"Engine folder: {plan['gufoPath']}", f"Parallel build jobs: {plan['jobs']}"]
    for package in plan.get("packages", []):
        detail = package.get("path") or package.get("version") or "system package"
        lines.append(f"  {package['action'].title()} {package['name']}: {detail}")
    for key in ("rock", "xrt", "vcpkg"):
        if key in plan:
            item = plan[key]
            lines.append(f"  {item['action'].title()} {key}: {item.get('path') or item.get('version', 'managed folder')}")
    if plan.get("missing"):
        lines.append("Missing prerequisites: " + ", ".join(plan["missing"]))
    if plan.get("systemPackages"):
        lines.append(f"Install with {plan.get('packageManager')}: " + " ".join(plan["systemPackages"]))
    if any(package.get("wingetId") and package.get("action") == "install" for package in plan.get("packages", [])):
        lines.append("Continuing accepts WinGet source and package agreements for the listed installations.")
    lines += ["", "Engine updates track upstream main; compatibility can change.",
              "Install/repair reuse the existing source revision; Update fetches main.",
              "Builds run in the engine checkout. If a build fails after pulling, the source update is retained.",
              "Stop the engine before continuing. Models and saved presets are preserved."]
    if plan.get("requiresSudo"):
        lines.append("System packages need sudo. Authentication takes place in the terminal before installation.")
    return "\n".join(lines)
