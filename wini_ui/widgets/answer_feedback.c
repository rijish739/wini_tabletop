/* answer_feedback — see answer_feedback.h. A tinted matte banner laid out as
 * [check][label]. The ✓ is drawn with an lv_line polyline rather than a glyph:
 * the bundled DejaVu Serif has no U+2713, and a drawn tick stays on-theme (ink
 * on paper) and always renders. ALMOST shows no mark by design. */
#include "widgets/answer_feedback.h"
#include "theme/wini_theme.h"

#include <stdlib.h>

#define TEXT_CORRECT "Correct"
#define TEXT_ALMOST  "Almost. We'll revisit this concept together."
#define TICK_BOX     24

/* lv_line references (does not copy) its points — fixed geometry, so static. */
static const lv_point_precise_t TICK_PTS[] = {
    { 4, 13 }, { 10, 19 }, { 20, 5 },
};

typedef struct {
    lv_obj_t *tick;
    lv_obj_t *label;
} fb_t;

static void free_cb(lv_event_t *e) { free(lv_event_get_user_data(e)); }

lv_obj_t *wini_answer_feedback_create(lv_obj_t *parent)
{
    fb_t *fb = calloc(1, sizeof(*fb));

    lv_obj_t *banner = lv_obj_create(parent);
    lv_obj_set_width(banner, LV_PCT(100));
    lv_obj_set_height(banner, LV_SIZE_CONTENT);
    lv_obj_set_style_radius(banner, WINI_RADIUS_CARD, 0);
    lv_obj_set_style_bg_opa(banner, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(banner, 0, 0);
    lv_obj_set_style_shadow_width(banner, 0, 0);
    lv_obj_set_style_pad_all(banner, WINI_PAD_CARD, 0);
    lv_obj_remove_flag(banner, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(banner, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(banner, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(banner, WINI_GAP_SM, 0);
    lv_obj_add_event_cb(banner, free_cb, LV_EVENT_DELETE, fb);

    /* Drawn tick (ink polyline). */
    fb->tick = lv_obj_create(banner);
    lv_obj_set_size(fb->tick, TICK_BOX, TICK_BOX);
    lv_obj_set_style_bg_opa(fb->tick, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(fb->tick, 0, 0);
    lv_obj_set_style_shadow_width(fb->tick, 0, 0);
    lv_obj_set_style_pad_all(fb->tick, 0, 0);
    lv_obj_remove_flag(fb->tick, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t *tick_line = lv_line_create(fb->tick);
    lv_line_set_points(tick_line, TICK_PTS, 3);
    lv_obj_set_style_line_width(tick_line, 3, 0);
    lv_obj_set_style_line_color(tick_line, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_line_rounded(tick_line, true, 0);

    fb->label = lv_label_create(banner);
    lv_obj_set_flex_grow(fb->label, 1);
    lv_label_set_long_mode(fb->label, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_font(fb->label, wini_font_body(), 0);
    lv_obj_set_style_text_color(fb->label, wini_color(WINI_COLOR_TEXT), 0);

    lv_obj_set_user_data(banner, fb);
    wini_answer_feedback_set(banner, WINI_FEEDBACK_CORRECT);
    return banner;
}

void wini_answer_feedback_set(lv_obj_t *fb_obj, wini_feedback_t kind)
{
    fb_t *fb = lv_obj_get_user_data(fb_obj);
    if (!fb) return;

    if (kind == WINI_FEEDBACK_ALMOST) {
        lv_obj_set_style_bg_color(fb_obj, wini_color(WINI_COLOR_TEST), 0);
        lv_obj_add_flag(fb->tick, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(fb->label, TEXT_ALMOST);
    } else {
        lv_obj_set_style_bg_color(fb_obj, wini_color(WINI_COLOR_SUCCESS), 0);
        lv_obj_remove_flag(fb->tick, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(fb->label, TEXT_CORRECT);
    }
}
