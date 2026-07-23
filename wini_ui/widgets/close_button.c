/* close_button — see close_button.h. */
#include "widgets/close_button.h"
#include "widgets/dialog.h"
#include "theme/wini_theme.h"

#include <stdio.h>
#include <stdlib.h>

/* The stop script is what run_wini_package.sh's sibling does by hand: kill
 * wini_ui + wini_client + wini_server, then resume touch_service.py. It is run
 * detached (setsid + &) so it survives us — it kills this very process. */
static void run_stop_script(void)
{
    const char *cmd = getenv("WINI_STOP_CMD");
    if (!cmd || !*cmd) cmd = "./stop_wini_package.sh";

    char buf[512];
    int n = snprintf(buf, sizeof(buf), "setsid sh -c '%s' >/dev/null 2>&1 &", cmd);
    if (n < 0 || n >= (int)sizeof(buf)) {
        fprintf(stderr, "[wini_ui] stop command too long; quitting UI only\n");
        return;
    }
    if (system(buf) != 0)
        fprintf(stderr, "[wini_ui] stop command failed; quitting UI only\n");
}

static void confirm_cb(lv_event_t *e)
{
    lv_obj_t *dlg = (lv_obj_t *)lv_event_get_user_data(e);
    wini_dialog_close(dlg);
    run_stop_script();
    wini_ui_request_quit();
}

static void cancel_cb(lv_event_t *e)
{
    wini_dialog_close((lv_obj_t *)lv_event_get_user_data(e));
}

static void tap_cb(lv_event_t *e)
{
    (void)e;
    /* On the top layer so the scrim covers the screens AND the floating pills. */
    lv_obj_t *dlg = wini_dialog_create(lv_layer_top(), "Finish for now?",
                                       "This closes Wini until you start it again.");
    wini_dialog_add_button(dlg, "Keep going", false, cancel_cb, dlg);
    wini_dialog_add_button(dlg, "Close Wini", true, confirm_cb, dlg);
}

lv_obj_t *wini_close_button_create(lv_obj_t *parent)
{
    lv_obj_t *btn = lv_button_create(parent);
    lv_obj_set_height(btn, WINI_TOUCH_MIN);
    lv_obj_set_width(btn, LV_SIZE_CONTENT);
    lv_obj_set_style_pad_hor(btn, WINI_PAD_CARD, 0);
    lv_obj_set_style_radius(btn, WINI_RADIUS_CHIP, 0);
    lv_obj_set_style_shadow_width(btn, 0, 0);
    lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(btn, wini_color(WINI_COLOR_CARD), 0);
    lv_obj_set_style_border_width(btn, 1, 0);
    lv_obj_set_style_border_color(btn, wini_color(WINI_COLOR_DIVIDER), 0);
    lv_obj_set_style_opa(btn, LV_OPA_90, LV_STATE_PRESSED);
    /* Mirrors the pause pill (bottom-RIGHT) on the opposite corner, so the two
     * destructive-ish controls are never adjacent to a mis-tap. */
    lv_obj_align(btn, LV_ALIGN_BOTTOM_LEFT, WINI_GAP,
                 -(WINI_FOOTER_H + WINI_GAP_SM));
    lv_obj_add_event_cb(btn, tap_cb, LV_EVENT_CLICKED, NULL);

    lv_obj_t *lbl = lv_label_create(btn);
    lv_obj_set_style_text_font(lbl, wini_font_body(), 0);
    lv_obj_set_style_text_color(lbl, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_label_set_text(lbl, "Close");
    lv_obj_center(lbl);
    return btn;
}
