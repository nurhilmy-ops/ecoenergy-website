#!/bin/bash
# Double-click this file to start the EcoEnergy terrain screening tool on this Mac.
# It installs what it needs the first time (5-10 minutes), then opens your web browser.
cd "$(dirname "$0")"
# Files unzipped from a download carry macOS's quarantine flag; clear it for this folder so the
# setup script and its files run without further "could not verify" prompts.
xattr -dr com.apple.quarantine . 2>/dev/null || true
export OPEN_BROWSER=1
if ! bash ./run_local.sh; then
  echo
  read -n 1 -s -r -p "  The tool stopped with an error. Read the message above, then press any key to close."
  echo
fi
