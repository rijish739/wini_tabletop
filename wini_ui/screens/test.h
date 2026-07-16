/* test — assessment (spec §Test). Deliberately STRIPPED: the shared frame and a
 * bare question card, nothing else. No hint dots, no feedback, no illustration —
 * during a test the screen must not coach. */
#ifndef WINI_SCREENS_TEST_H
#define WINI_SCREENS_TEST_H

#include "lvgl/lvgl.h"

lv_obj_t *wini_screen_test_create(lv_obj_t *parent);

#endif /* WINI_SCREENS_TEST_H */
