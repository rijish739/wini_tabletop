/* result_card — see result_card.h. */
#include "widgets/result_card.h"
#include "theme/wini_theme.h"

#include <stdlib.h>
#include <stdio.h>

typedef struct {
    lv_obj_t *score;
    lv_obj_t *caption;
} rcard_t;

static void free_cb(lv_event_t *e) { free(lv_event_get_user_data(e)); }

lv_obj_t *wini_result_card_create(lv_obj_t *parent)
{
    rcard_t *rc = calloc(1, sizeof(*rc));

    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_add_style(card, &wini_style_card, 0);
    lv_obj_set_width(card, LV_PCT(100));
    lv_obj_set_height(card, LV_SIZE_CONTENT);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_ver(card, WINI_PAD_CARD + WINI_GAP, 0);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(card, WINI_GAP_SM, 0);
    lv_obj_add_event_cb(card, free_cb, LV_EVENT_DELETE, rc);

    rc->score = lv_label_create(card);
    lv_obj_set_style_text_font(rc->score, wini_font_heading(), 0);
    lv_obj_set_style_text_color(rc->score, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_text_letter_space(rc->score, 2, 0);
    lv_label_set_text(rc->score, "");

    rc->caption = lv_label_create(card);
    lv_obj_set_style_text_font(rc->caption, wini_font_body(), 0);
    lv_obj_set_style_text_color(rc->caption, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_obj_set_style_text_align(rc->caption, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_text(rc->caption, "");

    lv_obj_set_user_data(card, rc);
    return card;
}

void wini_result_card_set(lv_obj_t *card, int score, int total,
                          const char *caption)
{
    rcard_t *rc = lv_obj_get_user_data(card);
    if (!rc) return;

    char buf[32];
    snprintf(buf, sizeof(buf), "%d / %d", score, total);
    lv_label_set_text(rc->score, buf);

    if (caption && caption[0]) {
        lv_label_set_text(rc->caption, caption);
        lv_obj_remove_flag(rc->caption, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(rc->caption, LV_OBJ_FLAG_HIDDEN);
    }
}
