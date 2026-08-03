/* status_chip — see status_chip.h. */
#include "widgets/status_chip.h"
#include "widgets/chip.h"

/* The label is stored as the chip's user_data so set() needs no heap; the dot's
 * tint is fixed (soft ink) — only the pill tint + word change per state. */

lv_obj_t *wini_status_chip_create(lv_obj_t *parent, wini_status_t status)
{
    lv_obj_t *chip = wini_chip_create(parent, wini_status_color(status));

    lv_obj_t *dot = lv_obj_create(chip);
    lv_obj_set_size(dot, 12, 12);
    lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(dot, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_50, 0);
    lv_obj_set_style_border_width(dot, 0, 0);
    lv_obj_set_style_shadow_width(dot, 0, 0);
    lv_obj_remove_flag(dot, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *lbl = lv_label_create(chip);
    lv_obj_set_style_text_font(lbl, wini_font_body(), 0);
    lv_obj_set_style_text_color(lbl, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(lbl, wini_status_label(status));

    lv_obj_set_user_data(chip, lbl);
    return chip;
}

void wini_status_chip_set(lv_obj_t *chip, wini_status_t status)
{
    lv_obj_set_style_bg_color(chip, wini_status_color(status), 0);
    lv_label_set_text((lv_obj_t *)lv_obj_get_user_data(chip),
                      wini_status_label(status));
}
