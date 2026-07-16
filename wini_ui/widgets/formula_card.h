/* formula_card — one equation, given room to breathe (spec §Cards / §Formula).
 *
 * Large, centered, generously spaced. Callers pass typeset math using real
 * glyphs (`x²`, `π`, `√`, `≤`) rather than ASCII (`x^2`) — the serif font
 * carries the math subset.
 */
#ifndef WINI_WIDGETS_FORMULA_CARD_H
#define WINI_WIDGETS_FORMULA_CARD_H

#include "lvgl/lvgl.h"

/* Create an empty formula card. Returns its root. */
lv_obj_t *wini_formula_card_create(lv_obj_t *parent);

/* Set the (UTF-8) formula string, centered. */
void wini_formula_card_set(lv_obj_t *card, const char *formula);

#endif /* WINI_WIDGETS_FORMULA_CARD_H */
