/* result_card — the end-of-stage score (spec §Cards / §Result).
 *
 * A large "4 / 5" score with a calm caption. No pass/fail language, no grades —
 * just the number and a gentle line.
 */
#ifndef WINI_WIDGETS_RESULT_CARD_H
#define WINI_WIDGETS_RESULT_CARD_H

#include "lvgl/lvgl.h"

/* Create an empty result card. Returns its root. */
lv_obj_t *wini_result_card_create(lv_obj_t *parent);

/* Set the score (`score` of `total`) and an optional caption (NULL to hide). */
void wini_result_card_set(lv_obj_t *card, int score, int total,
                          const char *caption);

#endif /* WINI_WIDGETS_RESULT_CARD_H */
