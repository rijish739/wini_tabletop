/* celebration — a brief, calm moment of praise (spec §Overlays).
 *
 * A soft success badge with a drawn ✓ and a short message. ONE gentle pulse,
 * then it fades itself away — no confetti, no particles, no bounce. Triggered
 * with wini_celebration_play (it shows and auto-hides itself).
 */
#ifndef WINI_OVERLAYS_CELEBRATION_H
#define WINI_OVERLAYS_CELEBRATION_H

#include "lvgl/lvgl.h"

/* Create the (hidden) celebration overlay inside `parent`. Returns its root. */
lv_obj_t *wini_celebration_create(lv_obj_t *parent);

/* Show it with `message` (e.g. "Well done"), pulse once, then auto-hide. */
void wini_celebration_play(lv_obj_t *ov, const char *message);

#endif /* WINI_OVERLAYS_CELEBRATION_H */
