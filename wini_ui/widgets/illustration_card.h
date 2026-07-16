/* illustration_card — a simple flat figure (spec §Illustrations).
 *
 * NCERT-textbook style: thin ink lines/arcs on paper, drawn with LVGL vector
 * primitives. No clipart, no 3D, no cartoons. Stage 2 ships one representative
 * figure (a circle with a labelled radius); real diagrams are parameterized in
 * a later stage.
 */
#ifndef WINI_WIDGETS_ILLUSTRATION_CARD_H
#define WINI_WIDGETS_ILLUSTRATION_CARD_H

#include "lvgl/lvgl.h"

/* Create an illustration card drawing the circle-with-radius figure. Returns
 * its root. */
lv_obj_t *wini_illustration_card_create(lv_obj_t *parent);

#endif /* WINI_WIDGETS_ILLUSTRATION_CARD_H */
