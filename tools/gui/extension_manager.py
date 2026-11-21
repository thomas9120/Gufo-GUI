"""Manage Gufo extension modules: catalog listing, validation, and async builds."""

from collections import deque
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

from extensions import clear_cache, inspect_executable
from settings import ROOT

if os.name == "nt":
    from windows_job import WindowsJob


_CATALOG_TIMEOUT_SECONDS = 20
_EXTENSION_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_REGISTRY_SPEC = re.compile(r"^([a-z][a-z0-9_]*)(@([0-9]+\.[0-9]+\.[0-9]+))?$")
_URL_PREFIXES = ("https://", "http://", "ssh://", "file://", "git@")


def parse_extension_source(raw):
    """Validate an install source and determine whether it needs explicit trust confirmation."""
    if not isinstance(raw, str) or any(ord(c) < 32 for c in raw):
        raise ValueError("Extension source: enter a single line of text.")
    text = raw.strip()
    if not text:
        raise ValueError("Extension source: enter a registry name, pinned Git URL, or local folder.")
    if text.startswith("-"):
        raise ValueError("Extension source: cannot start with '-'.")
    if text in ("install", "list", "update", "remove"):
        raise ValueError(f"Extension source: '{text}' is a subcommand, not an extension name.")

    if text.startswith(_URL_PREFIXES):
        at = text.rfind("@")
        if at == -1 or at + 1 == len(text) or (text.startswith("git@") and at < 4):
            raise ValueError(f"Pin a commit or tag: {text}@<commit-or-tag>.")
        return {"kind": "git", "source": text, "trusted": False}

    if _REGISTRY_SPEC.match(text):
        return {"kind": "registry", "source": text, "trusted": True}

    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        if not candidate.is_dir():
            raise ValueError("Extension folder: choose an existing directory.")
        return {"kind": "path", "source": str(candidate.resolve()), "trusted": False}

    raise ValueError(
        "Extension source: enter a registry name (e.g. lfm3), a pinned Git URL (url@commit), or a full folder path."
    )


def validate_extension_name(name):
    if not isinstance(name, str) or not _EXTENSION_NAME.match(name.strip()):
        raise ValueError("Extension name: use lowercase letters, digits, and underscores.")
    return name.strip()


def _load_windows_toolchain(root=ROOT):
    state_path = Path(root) / "build" / "windows-setup.json"
    try:
        data = json.loads(state_path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def build_extension_invocation(executable, subcommand_args, *, root=ROOT, windows=None):
    """Build (argv, env, cwd) for `gufo extension ...`, wrapping MSVC/ROCm env on Windows builds."""
    use_windows = (os.name == "nt") if windows is None else windows
    exe_path = Path(executable).expanduser()
    if not exe_path.is_absolute() or not exe_path.is_file():
        raise ValueError("Select an existing Gufo executable first.")
    cwd = exe_path.parent
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    needs_build_env = bool(subcommand_args) and subcommand_args[0] in ("install", "update")
    if use_windows and needs_build_env:
        state = _load_windows_toolchain(root)
        vs_path = state.get("VS") if isinstance(state.get("VS"), str) else ""
        vcvars = Path(vs_path) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat" if vs_path else None
        wrapper = Path(root) / "tools" / "windows" / "run-extension.cmd"
        if vcvars and vcvars.is_file() and wrapper.is_file():
            rocm = state.get("Rocm", "")
            vcpkg = state.get("Vcpkg", "")
            xrt = state.get("Xrt", "")
            path_entries = []
            vs_installer = Path(env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer"
            if vs_installer.is_dir():
                path_entries.append(str(vs_installer))
            if rocm:
                rocm_norm = rocm.replace("\\", "/")
                env["HIP_PATH"] = rocm_norm
                env["ROCM_PATH"] = rocm_norm
                env["HIP_DEVICE_LIB_PATH"] = f"{rocm_norm}/lib/llvm/amdgcn/bitcode"
                path_entries.extend((str(Path(rocm) / "bin"), str(Path(rocm) / "lib" / "llvm" / "bin")))
            if vcpkg:
                env["VCPKG_ROOT"] = vcpkg.replace("\\", "/")
            if xrt:
                env["XRT_DIR"] = xrt
            for tool_key in ("Git", "CMake", "Ninja", "Python"):
                tool_path = state.get(tool_key)
                if isinstance(tool_path, str) and tool_path:
                    path_entries.append(str(Path(tool_path).parent))
            if path_entries:
                env["PATH"] = os.pathsep.join(path_entries + [env.get("PATH", "")])
            env["GUFO_VCVARS"] = str(vcvars)
            env["GUFO_EXE"] = str(exe_path)
            env["GUFO_PYTHON"] = sys.executable
            env["GUFO_EXTENSION_ARGV_JSON"] = json.dumps([str(exe_path), "extension", *subcommand_args])
            return ["cmd.exe", "/d", "/c", "call", str(wrapper)], env, cwd
    return [str(exe_path), "extension", *subcommand_args], env, cwd


def list_catalog(executable):
    """Run `gufo extension list --json` on demand to include reviewed registry releases."""
    if not isinstance(executable, str) or not executable.strip():
        return {"available": False, "error": "Select a Gufo executable first.", "extensions": [], "registry_error": ""}
    exe_path = Path(executable.strip()).expanduser()
    if not exe_path.is_absolute() or not exe_path.is_file():
        return {"available": False, "error": "Gufo executable not found.", "extensions": [], "registry_error": ""}
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [str(exe_path), "extension", "list", "--json"],
            cwd=exe_path.parent,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CATALOG_TIMEOUT_SECONDS,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": f"Could not list Gufo extensions: {exc}", "extensions": [], "registry_error": ""}
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = lines[0] if lines else f"exit code {proc.returncode}"
        return {"available": False, "error": f"Extension catalog unavailable: {detail}", "extensions": [], "registry_error": ""}
    try:
        data = json.loads(proc.stdout)
        if not isinstance(data, dict):
            raise ValueError("unexpected payload")
    except ValueError:
        return {"available": False, "error": "Extension catalog returned invalid JSON.", "extensions": [], "registry_error": ""}
    entries = data.get("extensions") if isinstance(data.get("extensions"), list) else []
    return {
        "available": True,
        "error": "",
        "build_id": data.get("buildId", ""),
        "store": data.get("store", ""),
        "registry": data.get("registry", ""),
        "registry_error": data.get("registryError", "") if isinstance(data.get("registryError"), str) else "",
        "extensions": entries,
    }


class ExtensionJobManager:
    """Own one background `gufo extension` install/update/remove job with streamed logs and cancel."""

    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.process = None
        self.job = None
        self.state = "idle"  # idle | running | succeeded | failed | cancelled
        self.operation = ""
        self.target = ""
        self.executable = ""
        self.error = ""
        self.exit_code = None
        self.logs = deque(maxlen=400)
        self.started_at = None
        self.cancelled = False
        self.refreshed_extensions = None

    def is_running(self):
        with self.lock:
            return self.state == "running" and self.process is not None and self.process.poll() is None

    def snapshot(self):
        with self.lock:
            return {
                "state": self.state,
                "operation": self.operation,
                "target": self.target,
                "error": self.error,
                "exit_code": self.exit_code,
                "logs": list(self.logs),
                "elapsed_seconds": int(time.monotonic() - self.started_at) if self.started_at else 0,
                "extensions": self.refreshed_extensions,
            }

    def start(self, executable, operation, subcommand_args, target=""):
        argv, env, cwd = build_extension_invocation(executable, subcommand_args, root=self.root)
        with self.lock:
            if self.state == "running":
                raise ValueError("Wait for the current extension task to finish or cancel it first.")
            self.logs.clear()
            self.state = "running"
            self.operation = operation
            self.target = target
            self.executable = str(executable)
            self.error = ""
            self.exit_code = None
            self.started_at = time.monotonic()
            self.cancelled = False
            self.refreshed_extensions = None
            if self.job is not None:
                self.job.close()
                self.job = None
            child = None
            try:
                if os.name == "nt":
                    self.job = WindowsJob()
                child = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    env=env,
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    start_new_session=os.name != "nt",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if self.job is not None:
                    try:
                        self.job.assign(child)
                    except OSError:
                        if child.poll() is None:
                            raise
            except OSError as exc:
                if child is not None:
                    child.kill()
                    child.wait()
                    child.stdout.close()
                if self.job is not None:
                    self.job.close()
                    self.job = None
                self.state = "failed"
                self.error = f"Could not run gufo extension: {exc}"
                raise ValueError(self.error) from exc
            self.process = child
            threading.Thread(target=self._run_reader, args=(child, str(executable)), daemon=True).start()
            return self.snapshot()

    def _run_reader(self, child, executable):
        try:
            with child.stdout:
                while line := child.stdout.readline(4096):
                    with self.lock:
                        if self.process is child:
                            self.logs.append(line.rstrip("\r\n"))
            code = child.wait()
        except OSError:
            code = child.poll()
            if code is None:
                code = 1
        clear_cache()
        refreshed = None
        with self.lock:
            was_cancelled = self.cancelled
        if not was_cancelled and code == 0:
            refreshed = inspect_executable(executable, refresh=True)
        with self.lock:
            if self.process is child:
                if self.job is not None:
                    self.job.close()
                    self.job = None
                self.exit_code = code
                self.refreshed_extensions = refreshed
                if self.cancelled:
                    self.state = "cancelled"
                    self.error = "Extension task cancelled."
                elif code == 0:
                    self.state = "succeeded"
                else:
                    self.state = "failed"
                    self.error = f"gufo extension exited with code {code}. Check the build output below."

    def cancel(self):
        with self.lock:
            if self.state != "running" or self.process is None:
                return self.snapshot()
            self.cancelled = True
            child = self.process
            job = self.job
        try:
            if job is not None:
                job.terminate()
            elif child.poll() is None:
                if os.name == "nt":
                    child.kill()
                else:
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    child.kill()
                else:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                child.wait(timeout=3)
        except OSError:
            pass
        return self.snapshot()
