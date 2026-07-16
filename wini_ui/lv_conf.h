/* Minimal lv_conf.h for the Wini mode-select UI.
 *
 * Only OVERRIDES live here — LVGL's lv_conf_internal.h fills every macro we
 * leave undefined with its default, so this file stays tiny. Selected via the
 * CMake compile-define LV_CONF_PATH=<abs path to this file>.
 */
#ifndef LV_CONF_H
#define LV_CONF_H

/* 32-bit color to match the Pi's X11 framebuffer. */
#define LV_COLOR_DEPTH 32

/* SDL2 backend: an X11 window on the running desktop (visible over VNC). */
#define LV_USE_SDL 1
#define LV_SDL_INCLUDE_PATH <SDL2/SDL.h>

/* Heap headroom for the full widget tree (all screens are persistent). */
#define LV_MEM_SIZE (1024 * 1024U)

/* Tick source is provided in main.c via lv_tick_set_cb(). */

/* Text is the bundled DejaVu serif (theme/wini_theme.h, fonts/). montserrat_14
 * stays as LVGL's default + carries the LV_SYMBOL_* glyphs used for icons. */
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_20 1

/* Bring-up logging. */
#define LV_USE_LOG 1
#define LV_LOG_LEVEL LV_LOG_LEVEL_WARN

#endif /* LV_CONF_H */
