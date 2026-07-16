/* error — see error.h. */
#include "screens/error.h"
#include "screens/screen_mgr.h"
#include "theme/wini_theme.h"
#include "overlays/overlay_base.h"

lv_obj_t *wini_screen_error_create(lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    lv_obj_set_size(root, LV_PCT(100), LV_PCT(100));
    wini_theme_apply_screen(root);
    lv_obj_set_style_border_width(root, 0, 0);
    lv_obj_set_style_radius(root, 0, 0);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_set_flex_flow(root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(root, WINI_PAD_SCREEN, 0);
    lv_obj_set_style_pad_row(root, WINI_GAP, 0);

    /* A soft, slow pulse — reassuring, not an alarm. */
    wini_overlay_pulse_dot(root, wini_color(WINI_COLOR_THINKING), 28);

    lv_obj_t *title = lv_label_create(root);
    lv_obj_set_style_text_font(title, wini_font_heading(), 0);
    lv_obj_set_style_text_color(title, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(title, "Connection Lost");

    lv_obj_t *sub = lv_label_create(root);
    lv_obj_set_style_text_font(sub, wini_font_body(), 0);
    lv_obj_set_style_text_color(sub, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_label_set_text(sub, "Trying again\xe2\x80\xa6");   /* Trying again… */

    wini_nav_button(root, "Back home", WINI_SCREEN_IDLE, false);
    return root;
}
