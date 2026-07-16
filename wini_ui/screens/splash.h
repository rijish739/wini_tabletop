/* splash — the boot screen (spec §Boot).
 *
 * A quiet paper screen with the product name while the brain warms up. No
 * chrome, no spinner race — it fades itself to the idle home after a short beat.
 */
#ifndef WINI_SCREENS_SPLASH_H
#define WINI_SCREENS_SPLASH_H

#include "lvgl/lvgl.h"

lv_obj_t *wini_screen_splash_create(lv_obj_t *parent);

#endif /* WINI_SCREENS_SPLASH_H */
