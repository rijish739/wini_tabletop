/* stage_chip — see stage_chip.h. */
#include "widgets/stage_chip.h"
#include "widgets/chip.h"

/* The label is stored as the chip's user_data so set() needs no heap. */

lv_obj_t *wini_stage_chip_create(lv_obj_t *parent, wini_stage_t stage)
{
    lv_obj_t *chip = wini_chip_create(parent, wini_stage_color(stage));

    lv_obj_t *lbl = lv_label_create(chip);
    lv_obj_set_style_text_font(lbl, wini_font_body(), 0);
    lv_obj_set_style_text_color(lbl, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(lbl, wini_stage_label(stage));

    lv_obj_set_user_data(chip, lbl);
    return chip;
}

void wini_stage_chip_set(lv_obj_t *chip, wini_stage_t stage)
{
    lv_obj_set_style_bg_color(chip, wini_stage_color(stage), 0);
    lv_label_set_text((lv_obj_t *)lv_obj_get_user_data(chip),
                      wini_stage_label(stage));
}
