/* idle — the home launcher (spec §Home). The old dark mode_select re-skinned to
 * paper: a calm greeting and three soft stage cards (Explain / Practice / Test)
 * that open a session, plus a quiet Settings affordance. */
#ifndef WINI_SCREENS_IDLE_H
#define WINI_SCREENS_IDLE_H

#include "lvgl/lvgl.h"

lv_obj_t *wini_screen_idle_create(lv_obj_t *parent);

#endif /* WINI_SCREENS_IDLE_H */
