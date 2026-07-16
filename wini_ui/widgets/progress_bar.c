/* progress_bar — see progress_bar.h. Same segment approach as chrome/footer. */
#include "widgets/progress_bar.h"

#include <stdlib.h>

typedef struct {
    wini_stage_t stage;
    int          n;
    lv_obj_t    *seg[WINI_PROGRESS_MAX_SEG];
} bar_t;

static void free_cb(lv_event_t *e) { free(lv_event_get_user_data(e)); }

lv_obj_t *wini_progress_bar_create(lv_obj_t *parent, wini_stage_t stage,
                                   int segments)
{
    if (segments < 1) segments = 1;
    if (segments > WINI_PROGRESS_MAX_SEG) segments = WINI_PROGRESS_MAX_SEG;

    bar_t *b = calloc(1, sizeof(*b));
    b->stage = stage;
    b->n     = segments;

    lv_obj_t *bar = lv_obj_create(parent);
    lv_obj_set_size(bar, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(bar, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(bar, 0, 0);
    lv_obj_set_style_shadow_width(bar, 0, 0);
    lv_obj_set_style_pad_all(bar, 0, 0);
    lv_obj_set_style_pad_column(bar, 4, 0);
    lv_obj_remove_flag(bar, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(bar, LV_FLEX_FLOW_ROW);
    lv_obj_add_event_cb(bar, free_cb, LV_EVENT_DELETE, b);

    for (int i = 0; i < segments; i++) {
        lv_obj_t *s = lv_obj_create(bar);
        lv_obj_set_size(s, 18, 10);
        lv_obj_set_style_radius(s, 3, 0);
        lv_obj_set_style_border_width(s, 0, 0);
        lv_obj_set_style_shadow_width(s, 0, 0);
        lv_obj_set_style_bg_color(s, wini_color(WINI_COLOR_DIVIDER), 0);
        lv_obj_set_style_bg_opa(s, LV_OPA_COVER, 0);
        lv_obj_remove_flag(s, LV_OBJ_FLAG_SCROLLABLE);
        b->seg[i] = s;
    }

    lv_obj_set_user_data(bar, b);
    return bar;
}

void wini_progress_bar_set(lv_obj_t *bar, int done, int total)
{
    bar_t *b = lv_obj_get_user_data(bar);
    if (!b) return;

    int filled = 0;
    if (total > 0) {
        if (done < 0) done = 0;
        if (done > total) done = total;
        filled = (done * b->n + total / 2) / total;   /* round to nearest cell */
    }

    lv_color_t on  = wini_stage_color(b->stage);
    lv_color_t off = wini_color(WINI_COLOR_DIVIDER);
    for (int i = 0; i < b->n; i++)
        lv_obj_set_style_bg_color(b->seg[i], i < filled ? on : off, 0);
}
