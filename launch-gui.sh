#!/usr/bin/env bash
# Linux counterpart of launch-gui.bat.
bash "$(dirname -- "${BASH_SOURCE[0]}")/tools/linux/gui.sh" "$@"
exit_code=$?
if [[ $exit_code -eq 0 ]]; then exit 0; fi
echo
echo "Gufo launcher stopped with an error. See the message above."
exit "$exit_code"
