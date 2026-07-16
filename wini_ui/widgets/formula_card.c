/* formula_card — see formula_card.h. */
#include "widgets/formula_card.h"
#include "theme/wini_theme.h"

/* The formula label is the card's user_data so set() needs no heap. */

lv_obj_t *wini_formula_card_create(lv_obj_t *parent)
{
    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_add_style(card, &wini_style_card, 0);
    lv_obj_set_width(card, LV_PCT(100));
    lv_obj_set_height(card, LV_SIZE_CONTENT);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    /* generous vertical breathing room around the equation */
    lv_obj_set_style_pad_ver(card, WINI_PAD_CARD + WINI_GAP, 0);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    lv_obj_t *lbl = lv_label_create(card);
    lv_obj_set_width(lbl, LV_PCT(100));
    lv_label_set_long_mode(lbl, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_font(lbl, wini_font_heading(), 0);
    lv_obj_set_style_text_color(lbl, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_text_align(lbl, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_letter_space(lbl, 1, 0);
    lv_label_set_text(lbl, "");

    lv_obj_set_user_data(card, lbl);
    return card;
}

void wini_formula_card_set(lv_obj_t *card, const char *formula)
{
    lv_label_set_text((lv_obj_t *)lv_obj_get_user_data(card),
                      formula ? formula : "");
}
