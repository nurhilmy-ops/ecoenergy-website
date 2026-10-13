#!/bin/bash
# Double-click this file to start the EcoEnergy terrain screening tool on this Mac.
# It installs what it needs the first time (5-10 minutes), then opens your web browser.
cd "$(dirname "$0")"
export OPEN_BROWSER=1
if ! ./run_local.sh; then
  echo
  read -n 1 -s -r -p "  The tool stopped with an error. Read the message above, then press any key to close."
  echo
fi
