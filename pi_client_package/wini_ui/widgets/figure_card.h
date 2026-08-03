/* figure_card — a brain-driven image figure (T9 display channel).
 *
 * Shows one figure crop the brain selected for this turn (a PNG the client
 * resolved from its local store copy and wrote under /tmp), with the item's
 * alt_text as a caption. Driven only by the {"cmd":"figure"} IPC command —
 * it starts hidden and is hidden again on turns that carry no figure, so the
 * panel can never show a picture the brain didn't send.
 */
#ifndef WINI_WIDGETS_FIGURE_CARD_H
#define WINI_WIDGETS_FIGURE_CARD_H

#include "lvgl/lvgl.h"

/* Create the (hidden) figure card. Returns its root. */
lv_obj_t *wini_figure_card_create(lv_obj_t *parent);

/* Load `path` (an absolute filesystem path to a PNG), set the caption, and
 * show the card. A missing/unreadable file leaves the card hidden. */
void wini_figure_card_set(lv_obj_t *card, const char *path, const char *caption);

/* Hide the card (turn carries no figure). */
void wini_figure_card_clear(lv_obj_t *card);

#endif /* WINI_WIDGETS_FIGURE_CARD_H */
