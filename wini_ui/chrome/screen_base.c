/* screen_base — see screen_base.h. */
#include "chrome/screen_base.h"
#include "theme/wini_theme.h"

/* A fixed chrome band (header/footer): full width, no scroll, hairline divider
 * on the edge that faces the content. */
static lv_obj_t *band_create(lv_obj_t *parent, int32_t h, bool divider_below)
{
    lv_obj_t *b = lv_obj_create(parent);
    lv_obj_set_size(b, LV_PCT(100), h);
    lv_obj_set_style_bg_color(b, wini_color(WINI_COLOR_BG), 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(b, 0, 0);
    lv_obj_set_style_radius(b, 0, 0);
    lv_obj_set_style_shadow_width(b, 0, 0);
    lv_obj_set_style_pad_left(b, WINI_PAD_SCREEN, 0);
    lv_obj_set_style_pad_right(b, WINI_PAD_SCREEN, 0);
    lv_obj_set_style_pad_top(b, WINI_GAP_SM, 0);
    lv_obj_set_style_pad_bottom(b, WINI_GAP_SM, 0);
    lv_obj_remove_flag(b, LV_OBJ_FLAG_SCROLLABLE);

    /* hairline divider (matte, not a shadow) */
    lv_obj_set_style_border_color(b, wini_color(WINI_COLOR_DIVIDER), 0);
    lv_obj_set_style_border_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_border_side(
        b, divider_below ? LV_BORDER_SIDE_BOTTOM : LV_BORDER_SIDE_TOP, 0);
    lv_obj_set_style_border_width(b, 1, 0);
    return b;
}

void wini_frame_create(lv_obj_t *scr, wini_frame_t *out)
{
    wini_theme_apply_screen(scr);

    /* Vertical stack that fills the panel; no gaps — bands own their spacing. */
    lv_obj_set_flex_flow(scr, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(scr, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(scr, 0, 0);
    lv_obj_set_style_pad_row(scr, 0, 0);

    out->root   = scr;
    out->header = band_create(scr, WINI_HEADER_H, true);

    /* Content grows to fill the space between header and footer. */
    out->content = lv_obj_create(scr);
    lv_obj_set_width(out->content, LV_PCT(100));
    lv_obj_set_flex_grow(out->content, 1);
    lv_obj_set_style_bg_opa(out->content, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(out->content, 0, 0);
    lv_obj_set_style_radius(out->content, 0, 0);
    lv_obj_set_style_shadow_width(out->content, 0, 0);
    lv_obj_set_style_pad_all(out->content, WINI_PAD_SCREEN, 0);
    lv_obj_set_style_pad_row(out->content, WINI_GAP, 0);

    out->footer = band_create(scr, WINI_FOOTER_H, false);
}
