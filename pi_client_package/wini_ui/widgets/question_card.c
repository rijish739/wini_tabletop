/* question_card — see question_card.h. */
#include "widgets/question_card.h"
#include "theme/wini_theme.h"

#include <stdlib.h>

typedef struct {
    lv_obj_t *number;
    lv_obj_t *question;
    lv_obj_t *prompt;
} qcard_t;

static void free_cb(lv_event_t *e) { free(lv_event_get_user_data(e)); }

lv_obj_t *wini_question_card_create(lv_obj_t *parent)
{
    qcard_t *q = calloc(1, sizeof(*q));

    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_add_style(card, &wini_style_card, 0);
    lv_obj_set_width(card, LV_PCT(100));
    lv_obj_set_height(card, LV_SIZE_CONTENT);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    lv_obj_set_style_pad_row(card, WINI_GAP, 0);
    lv_obj_add_event_cb(card, free_cb, LV_EVENT_DELETE, q);

    q->number = lv_label_create(card);
    lv_obj_set_style_text_font(q->number, wini_font_body(), 0);
    lv_obj_set_style_text_color(q->number, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_label_set_text(q->number, "");

    q->question = lv_label_create(card);
    lv_obj_set_width(q->question, LV_PCT(100));
    lv_label_set_long_mode(q->question, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_font(q->question, wini_font_heading(), 0);
    lv_obj_set_style_text_color(q->question, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_text_line_space(q->question, 8, 0);
    lv_label_set_text(q->question, "");

    q->prompt = lv_label_create(card);
    lv_obj_set_style_text_font(q->prompt, wini_font_body(), 0);
    lv_obj_set_style_text_color(q->prompt, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_label_set_text(q->prompt, "Speak your answer");
    lv_obj_add_flag(q->prompt, LV_OBJ_FLAG_HIDDEN);

    lv_obj_set_user_data(card, q);
    return card;
}

void wini_question_card_set(lv_obj_t *card, const char *number,
                            const char *question)
{
    qcard_t *q = lv_obj_get_user_data(card);
    if (!q) return;

    if (number && number[0]) {
        lv_label_set_text(q->number, number);
        lv_obj_remove_flag(q->number, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(q->number, LV_OBJ_FLAG_HIDDEN);
    }
    lv_label_set_text(q->question, question ? question : "");
}

void wini_question_card_show_prompt(lv_obj_t *card, bool show)
{
    qcard_t *q = lv_obj_get_user_data(card);
    if (!q) return;
    if (show) lv_obj_remove_flag(q->prompt, LV_OBJ_FLAG_HIDDEN);
    else      lv_obj_add_flag(q->prompt, LV_OBJ_FLAG_HIDDEN);
}
