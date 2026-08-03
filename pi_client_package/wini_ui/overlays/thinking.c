/* thinking — see thinking.h. */
#include "overlays/thinking.h"
#include "overlays/overlay_base.h"
#include "theme/wini_theme.h"

/* The sub-state label is stored in the overlay's user_data (no heap). */

static void opa_exec_cb(void *obj, int32_t v)
{
    lv_obj_set_style_opa((lv_obj_t *)obj, (lv_opa_t)v, 0);
}

/* Three dots that pulse opacity in sequence (staggered delay), calm and endless. */
static void dots_row(lv_obj_t *parent)
{
    lv_obj_t *row = lv_obj_create(parent);
    lv_obj_set_size(row, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(row, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(row, 0, 0);
    lv_obj_set_style_shadow_width(row, 0, 0);
    lv_obj_set_style_pad_all(row, 0, 0);
    lv_obj_set_style_pad_column(row, 12, 0);
    lv_obj_remove_flag(row, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    for (int i = 0; i < 3; i++) {
        lv_obj_t *d = lv_obj_create(row);
        lv_obj_set_size(d, 16, 16);
        lv_obj_set_style_radius(d, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_color(d, wini_color(WINI_COLOR_THINKING), 0);
        lv_obj_set_style_bg_opa(d, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(d, 0, 0);
        lv_obj_set_style_shadow_width(d, 0, 0);
        lv_obj_remove_flag(d, LV_OBJ_FLAG_SCROLLABLE);

        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_var(&a, d);
        lv_anim_set_exec_cb(&a, opa_exec_cb);
        lv_anim_set_values(&a, LV_OPA_20, LV_OPA_COVER);
        lv_anim_set_duration(&a, 500);
        lv_anim_set_playback_duration(&a, 500);
        lv_anim_set_delay(&a, i * 250);
        lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
        lv_anim_start(&a);
    }
}

lv_obj_t *wini_thinking_create(lv_obj_t *parent)
{
    lv_obj_t *ov = wini_overlay_base_create(parent);

    dots_row(ov);

    lv_obj_t *title = lv_label_create(ov);
    lv_obj_set_style_text_font(title, wini_font_heading(), 0);
    lv_obj_set_style_text_color(title, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(title, "I'm thinking\xe2\x80\xa6");   /* … */

    lv_obj_t *sub = lv_label_create(ov);
    lv_obj_set_style_text_font(sub, wini_font_body(), 0);
    lv_obj_set_style_text_color(sub, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_label_set_text(sub, "");

    lv_obj_set_user_data(ov, sub);
    return ov;
}

void wini_thinking_set_substate(lv_obj_t *ov, wini_thinking_substate_t s)
{
    lv_obj_t *sub = lv_obj_get_user_data(ov);
    if (!sub) return;
    switch (s) {
        case WINI_THINKING_UNDERSTANDING:
            lv_label_set_text(sub, "Understanding your answer\xe2\x80\xa6"); break;
        case WINI_THINKING_SEARCHING:
            lv_label_set_text(sub, "Searching today's lesson\xe2\x80\xa6"); break;
        case WINI_THINKING_PREPARING:
            lv_label_set_text(sub, "Preparing explanation\xe2\x80\xa6"); break;
        case WINI_THINKING_NONE:
        default:
            lv_label_set_text(sub, ""); break;
    }
}
