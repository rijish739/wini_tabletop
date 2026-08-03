/* celebration — see celebration.h. */
#include "overlays/celebration.h"
#include "overlays/overlay_base.h"
#include "theme/wini_theme.h"

#include <stdlib.h>

#define BADGE 96
#define HOLD_MS 1600

/* lv_line references (does not copy) its points — fixed geometry, so static. */
static const lv_point_precise_t TICK_PTS[] = {
    { 30, 50 }, { 44, 64 }, { 68, 32 },
};

typedef struct {
    lv_obj_t *badge;
    lv_obj_t *message;
} cel_t;

static void free_cb(lv_event_t *e) { free(lv_event_get_user_data(e)); }

static void opa_exec_cb(void *obj, int32_t v)
{
    lv_obj_set_style_opa((lv_obj_t *)obj, (lv_opa_t)v, 0);
}

static void hide_timer_cb(lv_timer_t *t)
{
    wini_overlay_hide((lv_obj_t *)lv_timer_get_user_data(t));
}

lv_obj_t *wini_celebration_create(lv_obj_t *parent)
{
    cel_t *c = calloc(1, sizeof(*c));

    lv_obj_t *ov = wini_overlay_base_create(parent);
    lv_obj_add_event_cb(ov, free_cb, LV_EVENT_DELETE, c);

    /* Soft mint badge with a drawn tick (ink on mint). */
    c->badge = lv_obj_create(ov);
    lv_obj_set_size(c->badge, BADGE, BADGE);
    lv_obj_set_style_radius(c->badge, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(c->badge, wini_color(WINI_COLOR_SUCCESS), 0);
    lv_obj_set_style_bg_opa(c->badge, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(c->badge, 0, 0);
    lv_obj_set_style_shadow_width(c->badge, 0, 0);
    lv_obj_set_style_pad_all(c->badge, 0, 0);
    lv_obj_remove_flag(c->badge, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *tick = lv_line_create(c->badge);
    lv_line_set_points(tick, TICK_PTS, 3);
    lv_obj_set_style_line_width(tick, 6, 0);
    lv_obj_set_style_line_color(tick, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_line_rounded(tick, true, 0);

    c->message = lv_label_create(ov);
    lv_obj_set_style_text_font(c->message, wini_font_heading(), 0);
    lv_obj_set_style_text_color(c->message, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(c->message, "");

    lv_obj_set_user_data(ov, c);
    return ov;
}

void wini_celebration_play(lv_obj_t *ov, const char *message)
{
    cel_t *c = lv_obj_get_user_data(ov);
    if (!c) return;

    lv_label_set_text(c->message, message ? message : "Well done");
    wini_overlay_show(ov);

    /* One calm pulse on the badge (dim and back), no scaling. */
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, c->badge);
    lv_anim_set_exec_cb(&a, opa_exec_cb);
    lv_anim_set_values(&a, LV_OPA_COVER, LV_OPA_70);
    lv_anim_set_duration(&a, 300);
    lv_anim_set_playback_duration(&a, 300);
    lv_anim_set_repeat_count(&a, 1);
    lv_anim_start(&a);

    /* Auto-dismiss (one-shot timer). */
    lv_timer_t *t = lv_timer_create(hide_timer_cb, HOLD_MS, ov);
    lv_timer_set_repeat_count(t, 1);
}
