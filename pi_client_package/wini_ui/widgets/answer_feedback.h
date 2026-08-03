/* answer_feedback — the reply to an attempt (spec §Feedback, MANDATORY tone).
 *
 * Only two forms, both encouraging:
 *   CORRECT → soft-mint tint, "✓ Correct"
 *   ALMOST  → soft-orange tint, "Almost. We'll revisit this concept together."
 * NEVER "Wrong / Incorrect / Failed / Error" and never a red ✗ — a miss is a
 * shared next step, not a verdict.
 */
#ifndef WINI_WIDGETS_ANSWER_FEEDBACK_H
#define WINI_WIDGETS_ANSWER_FEEDBACK_H

#include "lvgl/lvgl.h"

typedef enum {
    WINI_FEEDBACK_CORRECT,
    WINI_FEEDBACK_ALMOST,
} wini_feedback_t;

/* Create a feedback banner (starts as CORRECT). Returns its root. */
lv_obj_t *wini_answer_feedback_create(lv_obj_t *parent);

/* Switch the banner between the two encouraging forms. */
void wini_answer_feedback_set(lv_obj_t *fb, wini_feedback_t kind);

#endif /* WINI_WIDGETS_ANSWER_FEEDBACK_H */
