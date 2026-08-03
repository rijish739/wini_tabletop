/* overlay_base — see overlay_base.h. */
#include "overlays/overlay_base.h"
#include "theme/wini_theme.h"

#define WINI_OVERLAY_FADE_MS 250

/* lv_anim exec: set an object's whole-object opacity. */
static void opa_exec_cb(void *obj, int32_t v)
{
    lv_obj_set_style_opa((lv_obj_t *)obj, (lv_opa_t)v, 0);
}

static void hide_done_cb(lv_anim_t *a)
{
    lv_obj_add_flag((lv_obj_t *)a->var, LV_OBJ_FLAG_HIDDEN);
}

lv_obj_t *wini_overlay_base_create(lv_obj_t *parent)
{
    lv_obj_t *ov = lv_obj_create(parent);
    lv_obj_set_size(ov, LV_PCT(100), LV_PCT(100));
    /* Cover regardless of a flex/scroll parent: opt out of layout, pin to 0,0. */
    lv_obj_add_flag(ov, LV_OBJ_FLAG_IGNORE_LAYOUT);
    lv_obj_align(ov, LV_ALIGN_CENTER, 0, 0);

    lv_obj_set_style_bg_color(ov, wini_color(WINI_COLOR_BG), 0);
    lv_obj_set_style_bg_opa(ov, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(ov, 0, 0);
    lv_obj_set_style_radius(ov, 0, 0);
    lv_obj_set_style_shadow_width(ov, 0, 0);
    lv_obj_set_style_pad_all(ov, WINI_PAD_SCREEN, 0);
    lv_obj_set_style_pad_row(ov, WINI_GAP, 0);
    lv_obj_remove_flag(ov, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(ov, LV_OBJ_FLAG_CLICKABLE);   /* eats taps on the content behind */

    lv_obj_set_flex_flow(ov, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(ov, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    /* Start fully hidden. */
    lv_obj_set_style_opa(ov, LV_OPA_TRANSP, 0);
    lv_obj_add_flag(ov, LV_OBJ_FLAG_HIDDEN);
    return ov;
}

void wini_overlay_show(lv_obj_t *ov)
{
    lv_obj_remove_flag(ov, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(ov);

    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, ov);
    lv_anim_set_exec_cb(&a, opa_exec_cb);
    lv_anim_set_values(&a, lv_obj_get_style_opa(ov, 0), LV_OPA_COVER);
    lv_anim_set_duration(&a, WINI_OVERLAY_FADE_MS);
    lv_anim_start(&a);
}

void wini_overlay_hide(lv_obj_t *ov)
{
    if (lv_obj_has_flag(ov, LV_OBJ_FLAG_HIDDEN)) return;

    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, ov);
    lv_anim_set_exec_cb(&a, opa_exec_cb);
    lv_anim_set_values(&a, lv_obj_get_style_opa(ov, 0), LV_OPA_TRANSP);
    lv_anim_set_duration(&a, WINI_OVERLAY_FADE_MS);
    lv_anim_set_completed_cb(&a, hide_done_cb);
    lv_anim_start(&a);
}

lv_obj_t *wini_overlay_pulse_dot(lv_obj_t *parent, lv_color_t color, int size)
{
    lv_obj_t *dot = lv_obj_create(parent);
    lv_obj_set_size(dot, size, size);
    lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(dot, color, 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(dot, 0, 0);
    lv_obj_set_style_shadow_width(dot, 0, 0);
    lv_obj_remove_flag(dot, LV_OBJ_FLAG_SCROLLABLE);

    /* Gentle, endless opacity breathing — no scaling. */
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, dot);
    lv_anim_set_exec_cb(&a, opa_exec_cb);
    lv_anim_set_values(&a, LV_OPA_30, LV_OPA_COVER);
    lv_anim_set_duration(&a, 800);
    lv_anim_set_playback_duration(&a, 800);
    lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
    lv_anim_start(&a);
    return dot;
}
