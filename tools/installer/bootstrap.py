"""Prepare the optional TUI environment; plain mode needs only the standard library."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[2]


def main():
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required")
    if (any(arg in sys.argv[1:] for arg in ("--plain", "--help", "-h", "--check-only"))
            or not (sys.stdin.isatty() and sys.stdout.isatty())):
        return subprocess.call([sys.executable, str(ROOT / "tools/installer/main.py"), *sys.argv[1:]])
    environment = ROOT / "build/installer-env"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    requirements = ROOT / "tools/installer/requirements.txt"
    stamp = environment / "requirements.sha256"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not python.is_file():
        print("Preparing the Gufo Setup environment...", flush=True)
        venv.create(environment, with_pip=True)
    ready = stamp.is_file() and stamp.read_text().strip() == digest
    if ready:
        ready = subprocess.call([str(python), "-c", "import textual"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL) == 0
    if not ready:
        stamp.unlink(missing_ok=True)
        subprocess.run([str(python), "-m", "ensurepip", "--upgrade"], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements)], check=True)
        stamp.write_text(digest, encoding="ascii")
    return subprocess.call([str(python), str(ROOT / "tools/installer/main.py"), *sys.argv[1:]])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Gufo Setup: {error}. On Linux, ensure python3-venv is installed.", file=sys.stderr)
        sys.exit(1)
