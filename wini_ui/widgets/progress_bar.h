/* progress_bar — a segmented stage-progress bar (spec §Footer / §Progress).
 *
 * Bars, never percentages ("Students understand progress bars faster"). Filled
 * segments take the stage tint; empty segments the hairline divider color. This
 * is the reusable form of the three bars the footer stacks; screens use it too.
 */
#ifndef WINI_WIDGETS_PROGRESS_BAR_H
#define WINI_WIDGETS_PROGRESS_BAR_H

#include "lvgl/lvgl.h"
#include "theme/wini_theme.h"

/* Create a segmented bar of `segments` cells tinted for `stage` (all empty).
 * `segments` is clamped to [1, WINI_PROGRESS_MAX_SEG]. Returns its root. */
lv_obj_t *wini_progress_bar_create(lv_obj_t *parent, wini_stage_t stage,
                                   int segments);

/* Fill `done` of `total` (clamped, rounded to whole segments). */
void wini_progress_bar_set(lv_obj_t *bar, int done, int total);

#define WINI_PROGRESS_MAX_SEG 12

#endif /* WINI_WIDGETS_PROGRESS_BAR_H */
