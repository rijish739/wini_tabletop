/* chip — see chip.h. Extracted from the inline chip builder that used to live in
 * chrome/header.c so stage_chip / status_chip share one pill definition. */
#include "widgets/chip.h"
#include "theme/wini_theme.h"

lv_obj_t *wini_chip_create(lv_obj_t *parent, lv_color_t bg)
{
    lv_obj_t *c = lv_obj_create(parent);
    lv_obj_set_height(c, LV_SIZE_CONTENT);
    lv_obj_set_width(c, LV_SIZE_CONTENT);
    lv_obj_set_style_bg_color(c, bg, 0);
    lv_obj_set_style_bg_opa(c, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(c, WINI_RADIUS_CHIP, 0);
    lv_obj_set_style_border_width(c, 0, 0);
    lv_obj_set_style_shadow_width(c, 0, 0);
    lv_obj_set_style_pad_hor(c, 16, 0);
    lv_obj_set_style_pad_ver(c, 8, 0);
    lv_obj_remove_flag(c, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(c, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(c, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(c, 8, 0);
    return c;
}
