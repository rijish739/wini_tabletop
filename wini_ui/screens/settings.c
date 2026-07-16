/* settings — see settings.h. */
#include "screens/settings.h"
#include "screens/screen_mgr.h"
#include "theme/wini_theme.h"

/* A matte row card: a serif label on the left, a muted value on the right. The
 * live sliders land in Stage 5; here the rows show the layout and current value. */
static void setting_row(lv_obj_t *parent, const char *label, const char *value)
{
    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_set_width(card, LV_PCT(100));
    lv_obj_set_height(card, LV_SIZE_CONTENT);
    lv_obj_add_style(card, &wini_style_card, 0);
    lv_obj_set_style_pad_all(card, WINI_PAD_CARD, 0);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_SPACE_BETWEEN,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    lv_obj_t *l = lv_label_create(card);
    lv_obj_set_style_text_font(l, wini_font_body(), 0);
    lv_obj_set_style_text_color(l, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(l, label);

    lv_obj_t *v = lv_label_create(card);
    lv_obj_set_style_text_font(v, wini_font_body(), 0);
    lv_obj_set_style_text_color(v, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_label_set_text(v, value);
}

lv_obj_t *wini_screen_settings_create(lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    lv_obj_set_size(root, LV_PCT(100), LV_PCT(100));
    wini_theme_apply_screen(root);
    lv_obj_set_style_border_width(root, 0, 0);
    lv_obj_set_style_radius(root, 0, 0);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_set_flex_flow(root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(root, WINI_PAD_SCREEN, 0);
    lv_obj_set_style_pad_row(root, WINI_GAP, 0);

    lv_obj_t *title = lv_label_create(root);
    lv_obj_set_style_text_font(title, wini_font_heading(), 0);
    lv_obj_set_style_text_color(title, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_pad_top(title, WINI_GAP_SM, 0);
    lv_label_set_text(title, "Settings");

    setting_row(root, "Brightness", "35%");
    setting_row(root, "Volume",     "Comfortable");
    setting_row(root, "Voice",      "On");

    /* A diagnostic entry to preview the connection-lost screen (real errors are
     * driven by the FSM in Stage 5). */
    wini_nav_button(root, "Check connection", WINI_SCREEN_ERROR, false);
    wini_nav_button(root, "Done", WINI_SCREEN_IDLE, true);
    return root;
}
