#!/usr/bin/env bash
# Start the optional local web launcher. The first run creates an isolated venv.
set -euo pipefail
port=8090 config="" no_browser=0 python="python3" prepare_only=0
while (( $# )); do
  case $1 in
    --port|--config|--python)
      if [[ $# -lt 2 ]]; then printf '%s needs a value.\n' "$1" >&2; exit 2; fi
      case $1 in --port) port=$2 ;; --config) config=$2 ;; --python) python=$2 ;; esac
      shift ;;
    --no-browser) no_browser=1 ;;
    --prepare-only) prepare_only=1 ;;
    -h|--help)
      printf 'Usage: launch-gui.sh [--port N] [--config PATH] [--no-browser] [--python PATH] [--prepare-only]\n'
      exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
environment="$root/build/gui-env"
venv_python="$environment/bin/python"
requirements="$root/tools/gui/requirements.txt"
stamp="$environment/gufo-requirements.sha256"
state_file="$root/build/linux-setup.json"
if [[ ! -x $venv_python && $python == python3 && -f $state_file ]]; then
  saved=$(python3 -I -c "import json,sys; print(json.load(open(sys.argv[1], encoding='utf-8-sig')).get('Python') or '')" \
    "$state_file" 2>/dev/null) || saved=""
  if [[ -n $saved && -x $saved ]]; then python=$saved; fi
fi
if [[ ! -x $venv_python ]]; then
  printf 'Creating the Gufo launcher environment (Python 3.10+ required)...\n'
  "$python" -I -c "import struct,sys; assert sys.version_info >= (3,10) and struct.calcsize('P') == 8, '64-bit Python 3.10+ is required'"
  if ! "$python" -m venv "$environment"; then
    printf 'Cannot create %s. On Debian/Ubuntu, install python3-venv first.\n' "$environment" >&2
    exit 1
  fi
fi
hash=$(sha256sum -- "$requirements" | cut -d ' ' -f 1)
installed_hash=""
if [[ -f $stamp ]]; then installed_hash=$(tr -d '[:space:]' <"$stamp"); fi
dependencies_ready=0
if [[ $installed_hash == "$hash" ]] && "$venv_python" -c "import flask, waitress" 2>/dev/null; then
  dependencies_ready=1
fi
if (( ! dependencies_ready )); then
  # A matching stamp does not guarantee that the installed packages are intact.
  rm -f -- "$stamp"
  # A cancelled first-time venv creation may leave Python present without pip.
  "$venv_python" -m ensurepip --upgrade
  "$venv_python" -m pip install --force-reinstall -r "$requirements"
  "$venv_python" -c "import flask, waitress"
  printf '%s\n' "$hash" >"$stamp"
fi
if (( prepare_only )); then exit 0; fi
arguments=("$root/tools/gui/server.py" --port "$port")
if [[ -n $config ]]; then arguments+=(--config "$config"); fi
if (( no_browser )); then arguments+=(--no-browser); fi
exec "$venv_python" "${arguments[@]}"
