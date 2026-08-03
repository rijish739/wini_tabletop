/* question_card — a practice/test question (spec §Cards).
 *
 * Muted "Question N of M" line, the question text large and wrapped, and an
 * optional calm "Speak your answer" affordance (voice-first — the card never
 * demands typing).
 */
#ifndef WINI_WIDGETS_QUESTION_CARD_H
#define WINI_WIDGETS_QUESTION_CARD_H

#include "lvgl/lvgl.h"

/* Create an empty question card (matte surface). Returns its root. */
lv_obj_t *wini_question_card_create(lv_obj_t *parent);

/* Set the number line (e.g. "Question 3 of 5"; pass NULL to hide it) and the
 * question text. */
void wini_question_card_set(lv_obj_t *card, const char *number,
                            const char *question);

/* Show or hide the "Speak your answer" prompt (hidden by default). */
void wini_question_card_show_prompt(lv_obj_t *card, bool show);

#endif /* WINI_WIDGETS_QUESTION_CARD_H */
