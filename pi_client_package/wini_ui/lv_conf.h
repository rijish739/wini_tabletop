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

/* Use the C library allocator (value 1 == LV_STDLIB_CLIB; the LV_STDLIB_* names
 * aren't defined yet when this file is included). The default BUILTIN allocator
 * is bounded by LV_MEM_SIZE, and decoding a full-page figure crop (~370 KB
 * ARGB) into that pool alongside all 8 persistent screens silently OOMs — the
 * PNG then draws blank. On the Pi we have GBs of RAM; malloc/free removes the
 * cap and lets the image cache grow/evict freely. (LV_MEM_SIZE is unused now.) */
#define LV_USE_STDLIB_MALLOC 1

/* Brain figure crops ({"cmd":"figure"}): POSIX file access under drive letter
 * 'A' ("A:/tmp/wini_fig_0.png") + the bundled lodepng PNG decoder. */
#define LV_USE_FS_POSIX 1
#define LV_FS_POSIX_LETTER 'A'
#define LV_FS_POSIX_PATH ""
#define LV_USE_LODEPNG 1

/* Tick source is provided in main.c via lv_tick_set_cb(). */

/* Text is the bundled DejaVu serif (theme/wini_theme.h, fonts/). montserrat_14
 * stays as LVGL's default + carries the LV_SYMBOL_* glyphs used for icons. */
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_20 1

/* Bring-up logging. */
#define LV_USE_LOG 1
#define LV_LOG_LEVEL LV_LOG_LEVEL_WARN

#endif /* LV_CONF_H */
