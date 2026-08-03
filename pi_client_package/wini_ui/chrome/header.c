/* header — see header.h. The stage/status pills are the reusable widgets/
 * stage_chip + status_chip; the header only owns the center block + layout. */
#include "chrome/header.h"
#include "widgets/stage_chip.h"
#include "widgets/status_chip.h"

#include <stdlib.h>

struct wini_header {
    lv_obj_t *stage_chip;
    lv_obj_t *line1;
    lv_obj_t *line2;
    lv_obj_t *status_chip;
};

static void free_cb(lv_event_t *e)
{
    free(lv_event_get_user_data(e));
}

wini_header_t *wini_header_create(lv_obj_t *band)
{
    wini_header_t *h = calloc(1, sizeof(*h));
    lv_obj_add_event_cb(band, free_cb, LV_EVENT_DELETE, h);

    /* header band lays its three parts out left / center / right */
    lv_obj_set_flex_flow(band, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(band, LV_FLEX_ALIGN_SPACE_BETWEEN,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(band, WINI_GAP, 0);

    /* --- Stage chip (left) --- */
    h->stage_chip = wini_stage_chip_create(band, WINI_STAGE_EXPLAIN);

    /* --- Center block (chapter / topic or "Question N of M") --- */
    lv_obj_t *center = lv_obj_create(band);
    lv_obj_set_height(center, LV_SIZE_CONTENT);
    lv_obj_set_flex_grow(center, 1);
    lv_obj_set_style_bg_opa(center, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(center, 0, 0);
    lv_obj_set_style_shadow_width(center, 0, 0);
    lv_obj_set_style_pad_all(center, 0, 0);
    lv_obj_remove_flag(center, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(center, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(center, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(center, 2, 0);

    h->line1 = lv_label_create(center);
    lv_obj_set_style_text_font(h->line1, wini_font_body(), 0);
    lv_obj_set_style_text_color(h->line1, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(h->line1, "");

    h->line2 = lv_label_create(center);
    lv_obj_set_style_text_font(h->line2, wini_font_body(), 0);
    lv_obj_set_style_text_color(h->line2, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_label_set_text(h->line2, "");

    /* --- Status chip (right) --- */
    h->status_chip = wini_status_chip_create(band, WINI_STATUS_WAITING);

    return h;
}

void wini_header_set_stage(wini_header_t *h, wini_stage_t stage)
{
    wini_stage_chip_set(h->stage_chip, stage);
}

void wini_header_set_status(wini_header_t *h, wini_status_t status)
{
    wini_status_chip_set(h->status_chip, status);
}

void wini_header_set_lines(wini_header_t *h, const char *line1, const char *line2)
{
    lv_label_set_text(h->line1, line1 ? line1 : "");
    lv_label_set_text(h->line2, line2 ? line2 : "");
}
