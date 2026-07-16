/* loading — a brief work-in-progress overlay (spec §Overlays).
 *
 * Shows what is happening in the learner's terms (e.g. "Getting your next
 * question…") — NEVER the word "Loading…". A calm pulsing dot above the line.
 * Show/hide via wini_overlay_show / wini_overlay_hide.
 */
#ifndef WINI_OVERLAYS_LOADING_H
#define WINI_OVERLAYS_LOADING_H

#include "lvgl/lvgl.h"

/* Create the (hidden) loading overlay inside `parent`. Returns its root. */
lv_obj_t *wini_loading_create(lv_obj_t *parent);

/* Set the intent line (what we're doing, in plain words — not "Loading…"). */
void wini_loading_set_text(lv_obj_t *ov, const char *intent);

#endif /* WINI_OVERLAYS_LOADING_H */
