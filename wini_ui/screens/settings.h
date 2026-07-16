/* settings — a small, calm settings page (spec §Settings). Not a session stage,
 * so it is a plain paper screen (no stage header): brightness / volume rows plus
 * a way back home. Live controls are wired in Stage 5. */
#ifndef WINI_SCREENS_SETTINGS_H
#define WINI_SCREENS_SETTINGS_H

#include "lvgl/lvgl.h"

lv_obj_t *wini_screen_settings_create(lv_obj_t *parent);

#endif /* WINI_SCREENS_SETTINGS_H */
