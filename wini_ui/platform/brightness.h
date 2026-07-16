/* brightness — the DSI backlight (spec §Brightness / §Comfort).
 *
 * The panel is a bedside device: the backlight is capped low (35%) and moved in
 * a short fade, never snapped. Best-effort over the Linux sysfs backlight class;
 * if no writable backlight node exists (permissions / headless), every call is a
 * clean no-op so the UI never blocks on it. On the ESP32-P4 this becomes a PWM
 * duty-cycle write instead. */
#ifndef WINI_PLATFORM_BRIGHTNESS_H
#define WINI_PLATFORM_BRIGHTNESS_H

#define WINI_BRIGHTNESS_CAP 35   /* hard ceiling, percent (spec) */

/* Discover the backlight node and set it to the resting level (cap). */
void wini_brightness_init(void);

/* Fade the backlight to `percent` (clamped to [0, WINI_BRIGHTNESS_CAP]) over a
 * short ramp. No-op if no writable node was found. */
void wini_brightness_set_percent(int percent);

#endif /* WINI_PLATFORM_BRIGHTNESS_H */
