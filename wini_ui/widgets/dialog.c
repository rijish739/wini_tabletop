/* dialog — see dialog.h. Root = a full-parent scrim; a centered card holds the
 * text and a button row. The scrim tint is the ink color at low opacity. */
#include "widgets/dialog.h"
#include "theme/wini_theme.h"

#include <stdlib.h>

typedef struct {
    lv_obj_t *card;
    lv_obj_t *buttons;   /* button row (created lazily on first add) */
} dlg_t;

static void free_cb(lv_event_t *e) { free(lv_event_get_user_data(e)); }

lv_obj_t *wini_dialog_create(lv_obj_t *parent, const char *title,
                             const char *msg)
{
    dlg_t *d = calloc(1, sizeof(*d));

    /* Scrim: dims the screen without a hard black. */
    lv_obj_t *scrim = lv_obj_create(parent);
    lv_obj_set_size(scrim, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_bg_color(scrim, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_bg_opa(scrim, LV_OPA_20, 0);
    lv_obj_set_style_border_width(scrim, 0, 0);
    lv_obj_set_style_radius(scrim, 0, 0);
    lv_obj_set_style_shadow_width(scrim, 0, 0);
    lv_obj_set_style_pad_all(scrim, WINI_PAD_SCREEN, 0);
    lv_obj_remove_flag(scrim, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(scrim, LV_OBJ_FLAG_CLICKABLE);   /* eat taps behind the card */
    lv_obj_set_flex_flow(scrim, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(scrim, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_add_event_cb(scrim, free_cb, LV_EVENT_DELETE, d);

    /* Card. */
    lv_obj_t *card = lv_obj_create(scrim);
    lv_obj_add_style(card, &wini_style_card, 0);
    lv_obj_set_width(card, LV_PCT(90));
    lv_obj_set_height(card, LV_SIZE_CONTENT);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    lv_obj_set_style_pad_row(card, WINI_GAP, 0);
    d->card = card;

    if (title && title[0]) {
        lv_obj_t *t = lv_label_create(card);
        lv_obj_set_width(t, LV_PCT(100));
        lv_label_set_long_mode(t, LV_LABEL_LONG_WRAP);
        lv_obj_set_style_text_font(t, wini_font_heading(), 0);
        lv_obj_set_style_text_color(t, wini_color(WINI_COLOR_TEXT), 0);
        lv_label_set_text(t, title);
    }
    if (msg && msg[0]) {
        lv_obj_t *m = lv_label_create(card);
        lv_obj_set_width(m, LV_PCT(100));
        lv_label_set_long_mode(m, LV_LABEL_LONG_WRAP);
        lv_obj_set_style_text_font(m, wini_font_body(), 0);
        lv_obj_set_style_text_color(m, wini_color(WINI_COLOR_TEXT), 0);
        lv_obj_set_style_text_line_space(m, 8, 0);
        lv_label_set_text(m, msg);
    }

    lv_obj_set_user_data(scrim, d);
    return scrim;
}

lv_obj_t *wini_dialog_add_button(lv_obj_t *dialog, const char *label,
                                 bool primary, lv_event_cb_t cb,
                                 void *user_data)
{
    dlg_t *d = lv_obj_get_user_data(dialog);
    if (!d) return NULL;

    if (!d->buttons) {
        d->buttons = lv_obj_create(d->card);
        lv_obj_set_width(d->buttons, LV_PCT(100));
        lv_obj_set_height(d->buttons, LV_SIZE_CONTENT);
        lv_obj_set_style_bg_opa(d->buttons, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_width(d->buttons, 0, 0);
        lv_obj_set_style_shadow_width(d->buttons, 0, 0);
        lv_obj_set_style_pad_all(d->buttons, 0, 0);
        lv_obj_set_style_pad_top(d->buttons, WINI_GAP_SM, 0);
        lv_obj_set_style_pad_column(d->buttons, WINI_GAP, 0);
        lv_obj_remove_flag(d->buttons, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_flex_flow(d->buttons, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(d->buttons, LV_FLEX_ALIGN_END,
                              LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    }

    lv_obj_t *btn = lv_button_create(d->buttons);
    lv_obj_set_height(btn, WINI_TOUCH_MIN);
    lv_obj_set_style_radius(btn, WINI_RADIUS_CHIP, 0);
    lv_obj_set_style_shadow_width(btn, 0, 0);
    lv_obj_set_style_pad_hor(btn, WINI_PAD_CARD, 0);
    if (primary) {
        lv_obj_set_style_bg_color(btn, wini_color(WINI_COLOR_EXPLAIN), 0);
        lv_obj_set_style_border_width(btn, 0, 0);
    } else {
        lv_obj_set_style_bg_color(btn, wini_color(WINI_COLOR_CARD), 0);
        lv_obj_set_style_border_width(btn, 1, 0);
        lv_obj_set_style_border_color(btn, wini_color(WINI_COLOR_DIVIDER), 0);
    }
    if (cb) lv_obj_add_event_cb(btn, cb, LV_EVENT_CLICKED, user_data);

    lv_obj_t *l = lv_label_create(btn);
    lv_obj_set_style_text_font(l, wini_font_body(), 0);
    lv_obj_set_style_text_color(l, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(l, label ? label : "");
    lv_obj_center(l);
    return btn;
}

void wini_dialog_close(lv_obj_t *dialog)
{
    if (dialog) lv_obj_delete(dialog);
}
