# display_env.sh — one place that knows whether this device is on Wayland or X11.
#
# Source it (`. pi_game/display_env.sh`), don't execute it. It exports the right
# display environment for the session that is actually running and defines the
# screenshot / synthetic-input helpers, so every script above it is
# backend-agnostic:
#
#     shot FILE                    screenshot the panel
#     tap  X Y                     tap at absolute panel coordinates
#     drag X0 Y0 X1 Y1 [steps] [pause]   press, move, release as one gesture
#
# winipi5 moved from X11 to labwc/Wayland on 2026-07-22. The X11 branch is kept
# because Xwayland still runs (the tutor's wini_ui is an X11 client) and because
# `raspi-config nonint do_wayland W1` + reboot puts the whole device back.

WINI_UID="$(id -u)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$WINI_UID}"

# Prefer Wayland when a compositor socket exists.
if [ -S "$XDG_RUNTIME_DIR/wayland-0" ]; then
    WINI_BACKEND=wayland
    export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
    # SDL2 has both backends compiled in and would otherwise pick X11 via
    # Xwayland — which works, but adds a translation layer between the Goodix
    # panel and LVGL for no benefit. Ask for Wayland explicitly.
    export SDL_VIDEODRIVER=wayland
    # xkbcommon spams "string literal is not a valid UTF-8 string" for every
    # line of the iso8859-1 Compose file when the locale is not UTF-8. Harmless,
    # but it buries real errors in the logs.
    export LC_ALL="${LC_ALL:-C.UTF-8}"
else
    WINI_BACKEND=x11
    export DISPLAY="${DISPLAY:-:0}"
    export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
fi
export WINI_BACKEND

ui_env() { :; }   # sourcing already exported everything a child needs

if [ "$WINI_BACKEND" = "wayland" ]; then
    shot() { grim "$1"; }
else
    shot() { scrot -o "$1"; }
fi

# Input goes through the kernel on BOTH backends (pi_game/touchsim.py): it
# registers a uinput multi-touch device, so events take the same path as a real
# finger and the helpers below behave identically on Wayland and X11.
#
# The pointer tools were tried first and are not adequate:
#   - wlrctl cannot drag at all. Each invocation creates a virtual pointer,
#     sends one action and destroys it, so a press and the motion after it come
#     from different devices and the compositor never sees a held drag. Measured:
#     the dragged object never left its resting coordinates.
#   - xdotool is X11-only.
TOUCHSIM="sudo $PWD/.venv/bin/python -m pi_game.touchsim"

tap()  { $TOUCHSIM tap "$1" "$2" >/dev/null; }
# drag FROM_X FROM_Y TO_X TO_Y [STEPS] [PAUSE] — one process owns the whole
# gesture, which is exactly why this works where wlrctl could not.
drag() { $TOUCHSIM drag "$1" "$2" "$3" "$4" \
             --steps "${5:-12}" --pause "${6:-0.05}" >/dev/null; }
