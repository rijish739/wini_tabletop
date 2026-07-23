/* lv_conf.h for the alphabet learning module.
 *
 * Only OVERRIDES live here; lv_conf_internal.h fills the rest. Selected via the
 * CMake define LV_CONF_PATH=<abs path>. Deliberately close to wini_ui/lv_conf.h —
 * same panel, same X11 stack, same PNG pipeline — so a fix in one is obvious in
 * the other.
 */
#ifndef LV_CONF_H
#define LV_CONF_H

/* 32-bit color to match the Pi's X11 framebuffer. */
#define LV_COLOR_DEPTH 32

/* SDL2 backend: an X11 window on the running desktop (also visible over VNC). */
#define LV_USE_SDL 1
#define LV_SDL_INCLUDE_PATH <SDL2/SDL.h>

/* CLib allocator, not the builtin pool. Every lesson holds several decoded PNGs
 * (a 180 px letter, a 420 px object, two robot faces) and LV_MEM_SIZE silently
 * OOMs on that, which shows up as blank images rather than an error — the exact
 * failure wini_ui hit with figure crops. */
#define LV_USE_STDLIB_MALLOC 1

/* Lesson art is loaded from disk by absolute path under drive letter 'A'
 * ("A:/home/winipi5/.../object.png") and decoded by the bundled lodepng. */
#define LV_USE_FS_POSIX 1
#define LV_FS_POSIX_LETTER 'A'
#define LV_FS_POSIX_PATH ""
#define LV_USE_LODEPNG 1

/* Images are scaled to fit their slot, so ask for the smooth transform. */
#define LV_DRAW_SW_SUPPORT_ARGB8888 1

/* Tick source is provided in main.c via lv_tick_set_cb(). */

/* Text is bundled Nunito (fonts/, generated with lv_font_conv). montserrat_14
 * stays for LVGL's default + the LV_SYMBOL_* glyphs. */
#define LV_FONT_MONTSERRAT_14 1

/* Bring-up logging. */
#define LV_USE_LOG 1
#define LV_LOG_LEVEL LV_LOG_LEVEL_WARN

#endif /* LV_CONF_H */
