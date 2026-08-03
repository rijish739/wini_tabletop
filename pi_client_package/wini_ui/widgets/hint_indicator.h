/* hint_indicator — how much help has been given, as dots (spec §Hints).
 *
 * Renders `○○○ → ●○○ → ●●○ → ●●●` — filled dots for hints spent, hollow for
 * hints remaining. NEVER shows "Hint Level N" text: the escalation must feel
 * gentle, not like a score going down.
 */
#ifndef WINI_WIDGETS_HINT_INDICATOR_H
#define WINI_WIDGETS_HINT_INDICATOR_H

#include "lvgl/lvgl.h"

/* Create an indicator with `dots` positions (clamped to [1, 6]), level 0. */
lv_obj_t *wini_hint_indicator_create(lv_obj_t *parent, int dots);

/* Set how many dots are filled (clamped to [0, dots]). */
void wini_hint_indicator_set(lv_obj_t *ind, int level);

#endif /* WINI_WIDGETS_HINT_INDICATOR_H */
