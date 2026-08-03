/* footer — see footer.h. Each stage's bar is a widgets/progress_bar; the footer
 * only stacks the three labelled columns. */
#include "chrome/footer.h"
#include "widgets/progress_bar.h"

#include <stdlib.h>

#define WINI_FOOTER_SEGMENTS 6
#define WINI_FOOTER_GROUPS   3   /* Explain, Practice, Test */

struct wini_footer {
    lv_obj_t    *bar[WINI_FOOTER_GROUPS];
    wini_stage_t stage_of[WINI_FOOTER_GROUPS];
};

static void free_cb(lv_event_t *e) { free(lv_event_get_user_data(e)); }

/* One labelled segmented bar (a stage's progress). */
static void group_create(lv_obj_t *parent, wini_footer_t *f, int gi,
                         wini_stage_t stage)
{
    f->stage_of[gi] = stage;

    lv_obj_t *col = lv_obj_create(parent);
    lv_obj_set_size(col, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(col, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(col, 0, 0);
    lv_obj_set_style_shadow_width(col, 0, 0);
    lv_obj_set_style_pad_all(col, 0, 0);
    lv_obj_set_style_pad_row(col, 6, 0);
    lv_obj_remove_flag(col, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(col, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(col, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    lv_obj_t *lbl = lv_label_create(col);
    lv_obj_set_style_text_font(lbl, wini_font_body(), 0);
    lv_obj_set_style_text_color(lbl, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_label_set_text(lbl, wini_stage_label(stage));

    f->bar[gi] = wini_progress_bar_create(col, stage, WINI_FOOTER_SEGMENTS);
}

wini_footer_t *wini_footer_create(lv_obj_t *band)
{
    wini_footer_t *f = calloc(1, sizeof(*f));
    lv_obj_add_event_cb(band, free_cb, LV_EVENT_DELETE, f);

    lv_obj_set_flex_flow(band, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(band, LV_FLEX_ALIGN_SPACE_EVENLY,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    group_create(band, f, 0, WINI_STAGE_EXPLAIN);
    group_create(band, f, 1, WINI_STAGE_PRACTICE);
    group_create(band, f, 2, WINI_STAGE_TEST);
    return f;
}

void wini_footer_set_progress(wini_footer_t *f, wini_stage_t stage,
                              int done, int total)
{
    for (int i = 0; i < WINI_FOOTER_GROUPS; i++)
        if (f->stage_of[i] == stage) {
            wini_progress_bar_set(f->bar[i], done, total);
            return;
        }
}
