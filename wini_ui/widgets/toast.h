/* toast — a brief, self-dismissing note (spec §Toasts).
 *
 * A small matte pill near the bottom that fades in, holds, and fades out on its
 * own. Calm and non-blocking — for confirmations, never for errors phrased as
 * failure.
 */
#ifndef WINI_WIDGETS_TOAST_H
#define WINI_WIDGETS_TOAST_H

#include "lvgl/lvgl.h"

/* Show a toast with `msg` over `parent`. It removes itself; returns the object
 * (usually ignored). */
lv_obj_t *wini_toast_show(lv_obj_t *parent, const char *msg);

#endif /* WINI_WIDGETS_TOAST_H */
