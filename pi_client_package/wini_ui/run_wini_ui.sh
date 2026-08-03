#!/usr/bin/env bash
# Launch the Wini touch UI on the Pi's DSI panel (X11 desktop).
# The picker connects to the wini_client mode channel (default 127.0.0.1:8140).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
exec "$DIR/build/wini_ui" "$@"
