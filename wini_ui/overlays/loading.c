/* loading — see loading.h. */
#include "overlays/loading.h"
#include "overlays/overlay_base.h"
#include "theme/wini_theme.h"

/* The intent label is stored in the overlay's user_data (no heap). */

lv_obj_t *wini_loading_create(lv_obj_t *parent)
{
    lv_obj_t *ov = wini_overlay_base_create(parent);

    wini_overlay_pulse_dot(ov, wini_color(WINI_COLOR_THINKING), 24);

    lv_obj_t *intent = lv_label_create(ov);
    lv_obj_set_width(intent, LV_PCT(90));
    lv_label_set_long_mode(intent, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_font(intent, wini_font_heading(), 0);
    lv_obj_set_style_text_color(intent, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_text_align(intent, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_text(intent, "");

    lv_obj_set_user_data(ov, intent);
    return ov;
}

void wini_loading_set_text(lv_obj_t *ov, const char *intent)
{
    lv_obj_t *lbl = lv_obj_get_user_data(ov);
    if (lbl) lv_label_set_text(lbl, intent ? intent : "");
}
