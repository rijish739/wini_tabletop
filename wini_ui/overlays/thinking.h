/* thinking — the "I'm thinking…" voice-state overlay (spec §Overlays).
 *
 * Three softly sequenced dots over "I'm thinking…" with a changeable sub-state
 * line. The sub-state copy is fixed by the spec, so callers pick from the enum
 * rather than passing free text. Show/hide via wini_overlay_show / _hide.
 */
#ifndef WINI_OVERLAYS_THINKING_H
#define WINI_OVERLAYS_THINKING_H

#include "lvgl/lvgl.h"

typedef enum {
    WINI_THINKING_NONE,            /* no sub-line                          */
    WINI_THINKING_UNDERSTANDING,   /* "Understanding your answer…"         */
    WINI_THINKING_SEARCHING,       /* "Searching today's lesson…"          */
    WINI_THINKING_PREPARING,       /* "Preparing explanation…"             */
} wini_thinking_substate_t;

/* Create the (hidden) thinking overlay inside `parent`. Returns its root. */
lv_obj_t *wini_thinking_create(lv_obj_t *parent);

/* Swap the sub-state line (the exact spec copy for each). */
void wini_thinking_set_substate(lv_obj_t *ov, wini_thinking_substate_t s);

#endif /* WINI_OVERLAYS_THINKING_H */
