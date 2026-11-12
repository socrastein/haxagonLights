#!/usr/bin/env bash
# Opens the Haxagon Lights control page, first starting the bridge if nothing is answering on its
# port. Run by the taskbar launcher; see "Taskbar launcher" in ../CLAUDE.md.
set -euo pipefail

repo_directory="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
page_url="http://127.0.0.1:8765"
bridge_log="$HOME/.cache/haxagon-lights.log"
startup_checks=50 # Checked every 0.1 seconds: the bridge normally answers in well under a second.

# True when the bridge answers; the status endpoint needs no Bluetooth, so it is cheap to ask.
bridge_is_running() {
  curl -fs --max-time 1 "$page_url/api/status" >/dev/null
}

# Starts the bridge detached from this script, so it keeps running after the launcher exits.
start_bridge() {
  setsid nohup "$repo_directory/.venv/bin/python" "$repo_directory/bridge/server.py" \
    >"$bridge_log" 2>&1 &
}

# Waits until the bridge answers, so the page never opens onto a connection error.
wait_for_bridge() {
  for _ in $(seq "$startup_checks"); do
    bridge_is_running && return 0
    sleep 0.1
  done
  echo "The bridge did not start; see $bridge_log" >&2
  return 1
}

if ! bridge_is_running; then
  start_bridge
  wait_for_bridge
fi
exec firefox --new-window "$page_url"
