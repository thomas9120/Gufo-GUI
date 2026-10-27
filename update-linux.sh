#!/usr/bin/env bash
# Linux counterpart of update-windows.bat.
bash "$(dirname -- "${BASH_SOURCE[0]}")/tools/linux/update.sh" "$@"
exit_code=$?
if [[ $exit_code -eq 0 ]]; then exit 0; fi
echo
echo "Gufo update stopped. Read the message above, then run ./update-linux.sh again."
exit "$exit_code"
