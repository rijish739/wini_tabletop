/* explanation_card — a single teaching beat (spec §Cards / §Explain).
 *
 * A large serif title and a short wrapped body (≤ 40–60 words by design — the
 * voice carries the detail; the card only anchors it). Matte surface.
 */
#ifndef WINI_WIDGETS_EXPLANATION_CARD_H
#define WINI_WIDGETS_EXPLANATION_CARD_H

#include "lvgl/lvgl.h"

/* Create an empty explanation card. Returns its root. */
lv_obj_t *wini_explanation_card_create(lv_obj_t *parent);

/* Set the title (heading) and the short body (wrapped). Pass NULL for empty. */
void wini_explanation_card_set(lv_obj_t *card, const char *title,
                               const char *body);

#endif /* WINI_WIDGETS_EXPLANATION_CARD_H */
