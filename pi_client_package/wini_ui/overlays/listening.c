/* listening — see listening.h. */
#include "overlays/listening.h"
#include "overlays/overlay_base.h"
#include "theme/wini_theme.h"

lv_obj_t *wini_listening_create(lv_obj_t *parent)
{
    lv_obj_t *ov = wini_overlay_base_create(parent);

    wini_overlay_pulse_dot(ov, wini_color(WINI_COLOR_LISTENING), 28);

    lv_obj_t *title = lv_label_create(ov);
    lv_obj_set_style_text_font(title, wini_font_heading(), 0);
    lv_obj_set_style_text_color(title, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(title, "I'm listening");

    lv_obj_t *sub = lv_label_create(ov);
    lv_obj_set_style_text_font(sub, wini_font_body(), 0);
    lv_obj_set_style_text_color(sub, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_label_set_text(sub, "Speak naturally.");

    return ov;
}
