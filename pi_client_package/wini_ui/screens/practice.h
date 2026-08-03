/* practice — guided practice (spec §Practice). Shared frame + a question card,
 * the gentle hint dots, and encouraging feedback. A listening overlay is parented
 * to the CONTENT region (not lv_layer_top) so the header/footer stay visible. */
#ifndef WINI_SCREENS_PRACTICE_H
#define WINI_SCREENS_PRACTICE_H

#include "lvgl/lvgl.h"

lv_obj_t *wini_screen_practice_create(lv_obj_t *parent);

#endif /* WINI_SCREENS_PRACTICE_H */
