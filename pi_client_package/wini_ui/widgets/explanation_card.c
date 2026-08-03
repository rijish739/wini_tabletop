/* explanation_card — see explanation_card.h. */
#include "widgets/explanation_card.h"
#include "theme/wini_theme.h"

#include <stdlib.h>

typedef struct {
    lv_obj_t *title;
    lv_obj_t *body;
} ecard_t;

static void free_cb(lv_event_t *e) { free(lv_event_get_user_data(e)); }

lv_obj_t *wini_explanation_card_create(lv_obj_t *parent)
{
    ecard_t *ec = calloc(1, sizeof(*ec));

    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_add_style(card, &wini_style_card, 0);
    lv_obj_set_width(card, LV_PCT(100));
    lv_obj_set_height(card, LV_SIZE_CONTENT);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    lv_obj_set_style_pad_row(card, WINI_GAP, 0);
    lv_obj_add_event_cb(card, free_cb, LV_EVENT_DELETE, ec);

    ec->title = lv_label_create(card);
    lv_obj_set_width(ec->title, LV_PCT(100));
    lv_label_set_long_mode(ec->title, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_font(ec->title, wini_font_heading(), 0);
    lv_obj_set_style_text_color(ec->title, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(ec->title, "");

    ec->body = lv_label_create(card);
    lv_obj_set_width(ec->body, LV_PCT(100));
    lv_label_set_long_mode(ec->body, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_font(ec->body, wini_font_body(), 0);
    lv_obj_set_style_text_color(ec->body, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_text_line_space(ec->body, 8, 0);
    lv_label_set_text(ec->body, "");

    lv_obj_set_user_data(card, ec);
    return card;
}

void wini_explanation_card_set(lv_obj_t *card, const char *title,
                               const char *body)
{
    ecard_t *ec = lv_obj_get_user_data(card);
    if (!ec) return;
    lv_label_set_text(ec->title, title ? title : "");
    lv_label_set_text(ec->body, body ? body : "");
}
