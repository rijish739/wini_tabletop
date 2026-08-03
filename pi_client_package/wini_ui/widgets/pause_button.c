/* pause_button — see pause_button.h. */
#include "widgets/pause_button.h"
#include "theme/wini_theme.h"
#include "app/app_state.h"
#include "ipc.h"

#include <stdbool.h>

/* One global toggle (the device has one mic); the label is the button's only
 * mutable child so no heap struct is needed. */
static bool s_paused = false;

static void restyle(lv_obj_t *btn)
{
    lv_obj_t *lbl = (lv_obj_t *)lv_obj_get_user_data(btn);
    if (s_paused) {
        /* Muted state: soft-orange tint so it reads at a glance. */
        lv_obj_set_style_bg_color(btn, wini_color(WINI_COLOR_TEST), 0);
        lv_label_set_text(lbl, "Mic off - resume");
    } else {
        lv_obj_set_style_bg_color(btn, wini_color(WINI_COLOR_CARD), 0);
        lv_label_set_text(lbl, "Pause");
    }
}

static void tap_cb(lv_event_t *e)
{
    lv_obj_t *btn = (lv_obj_t *)lv_event_get_target(e);
    s_paused = !s_paused;
    ipc_send_pause(s_paused ? 1 : 0);   /* best-effort; UI reflects intent */
    /* Reflect the mute on the current screen's status chip immediately (we're
     * on the LVGL thread, so dispatching locally is safe). */
    wini_app_dispatch(s_paused ? "{\"cmd\":\"status\",\"v\":\"offline\"}"
                               : "{\"cmd\":\"status\",\"v\":\"listening\"}");
    restyle(btn);
}

lv_obj_t *wini_pause_button_create(lv_obj_t *parent)
{
    lv_obj_t *btn = lv_button_create(parent);
    lv_obj_set_height(btn, WINI_TOUCH_MIN);
    lv_obj_set_width(btn, LV_SIZE_CONTENT);
    lv_obj_set_style_pad_hor(btn, WINI_PAD_CARD, 0);
    lv_obj_set_style_radius(btn, WINI_RADIUS_CHIP, 0);
    lv_obj_set_style_shadow_width(btn, 0, 0);
    lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(btn, 1, 0);
    lv_obj_set_style_border_color(btn, wini_color(WINI_COLOR_DIVIDER), 0);
    lv_obj_set_style_opa(btn, LV_OPA_90, LV_STATE_PRESSED);
    /* Float just above the footer band, clear of the TEST progress group. */
    lv_obj_align(btn, LV_ALIGN_BOTTOM_RIGHT, -WINI_GAP,
                 -(WINI_FOOTER_H + WINI_GAP_SM));
    lv_obj_add_event_cb(btn, tap_cb, LV_EVENT_CLICKED, NULL);

    lv_obj_t *lbl = lv_label_create(btn);
    lv_obj_set_style_text_font(lbl, wini_font_body(), 0);
    lv_obj_set_style_text_color(lbl, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_center(lbl);
    lv_obj_set_user_data(btn, lbl);

    restyle(btn);
    return btn;
}
