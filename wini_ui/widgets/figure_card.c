/* figure_card — see figure_card.h. */
#include "widgets/figure_card.h"
#include "theme/wini_theme.h"

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

typedef struct {
    lv_obj_t *img;
    lv_obj_t *caption;
    char      src[288];   /* "A:<abs path>" — lv_image references it by content */
} fcard_t;

static void free_cb(lv_event_t *e) { free(lv_event_get_user_data(e)); }

lv_obj_t *wini_figure_card_create(lv_obj_t *parent)
{
    fcard_t *fc = calloc(1, sizeof(*fc));

    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_add_style(card, &wini_style_card, 0);
    lv_obj_set_width(card, LV_PCT(100));
    lv_obj_set_height(card, LV_SIZE_CONTENT);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(card, WINI_GAP_SM, 0);
    lv_obj_add_event_cb(card, free_cb, LV_EVENT_DELETE, fc);

    fc->img = lv_image_create(card);

    fc->caption = lv_label_create(card);
    lv_obj_set_width(fc->caption, LV_PCT(100));
    lv_label_set_long_mode(fc->caption, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_font(fc->caption, wini_font_body(), 0);
    lv_obj_set_style_text_color(fc->caption, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_obj_set_style_text_align(fc->caption, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_text(fc->caption, "");

    lv_obj_set_user_data(card, fc);
    lv_obj_add_flag(card, LV_OBJ_FLAG_HIDDEN);
    return card;
}

void wini_figure_card_set(lv_obj_t *card, const char *path, const char *caption)
{
    fcard_t *fc = lv_obj_get_user_data(card);
    if (!fc || !path || access(path, R_OK) != 0) return;

    snprintf(fc->src, sizeof(fc->src), "%c:%s", LV_FS_POSIX_LETTER, path);
    /* The client cycles a small set of /tmp filenames, so the same src string
     * can carry NEW pixels — drop any cached decode before (re)setting it. */
    lv_image_cache_drop(fc->src);
    lv_image_set_src(fc->img, fc->src);

    if (caption && caption[0]) {
        lv_label_set_text(fc->caption, caption);
        lv_obj_remove_flag(fc->caption, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(fc->caption, LV_OBJ_FLAG_HIDDEN);
    }
    lv_obj_remove_flag(card, LV_OBJ_FLAG_HIDDEN);
}

void wini_figure_card_clear(lv_obj_t *card)
{
    lv_obj_add_flag(card, LV_OBJ_FLAG_HIDDEN);
}
