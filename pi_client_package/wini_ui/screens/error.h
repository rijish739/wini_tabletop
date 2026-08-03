/* error — the connection-lost screen (spec §Error). Calm, never alarming: a plain
 * paper screen, a soft pulsing dot, "Connection Lost" / "Trying again…", and a
 * way home. No red, no icons shouting. */
#ifndef WINI_SCREENS_ERROR_H
#define WINI_SCREENS_ERROR_H

#include "lvgl/lvgl.h"

lv_obj_t *wini_screen_error_create(lv_obj_t *parent);

#endif /* WINI_SCREENS_ERROR_H */
