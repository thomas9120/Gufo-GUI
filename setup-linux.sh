#!/usr/bin/env bash
# Linux counterpart of setup-windows.bat.
bash "$(dirname -- "${BASH_SOURCE[0]}")/tools/linux/setup.sh" "$@"
exit_code=$?
if [[ $exit_code -eq 0 ]]; then exit 0; fi
echo
echo "Gufo setup stopped. Read the message above, then run ./setup-linux.sh again."
exit "$exit_code"
