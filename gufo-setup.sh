#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if ! command -v python3 >/dev/null || ! python3 -I -c 'import struct,sys; assert sys.version_info >= (3,10) and struct.calcsize("P") == 8' 2>/dev/null; then
  printf 'Install 64-bit Python 3.10+ and venv support with your package manager, then rerun this file.\n' >&2
  exit 1
fi
exec python3 "$root/tools/installer/bootstrap.py" "$@"
