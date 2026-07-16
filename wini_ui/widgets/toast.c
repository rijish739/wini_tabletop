/* toast — see toast.h. Appears, holds, then dissolves and deletes itself via the
 * LVGL fade-out + delayed-delete timers (no callback bookkeeping needed).
 *
 * NOTE: lv_obj_fade_in leaves the object at opacity 0 here (its early-apply sets
 * 0 and the in-animation does not visibly complete), so the toast is shown at
 * full opacity immediately — the calm moment that matters is the dissolve. */
#include "widgets/toast.h"
#include "theme/wini_theme.h"

#define TOAST_IN    200
#define TOAST_HOLD 1800
#define TOAST_OUT   300

lv_obj_t *wini_toast_show(lv_obj_t *parent, const char *msg)
{
    lv_obj_t *pill = lv_obj_create(parent);
    lv_obj_set_size(pill, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_style_max_width(pill, LV_PCT(90), 0);
    lv_obj_set_style_radius(pill, WINI_RADIUS_CHIP, 0);
    lv_obj_set_style_bg_color(pill, wini_color(WINI_COLOR_THINKING), 0);
    lv_obj_set_style_bg_opa(pill, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(pill, 1, 0);
    lv_obj_set_style_border_color(pill, wini_color(WINI_COLOR_DIVIDER), 0);
    lv_obj_set_style_shadow_width(pill, 0, 0);
    lv_obj_set_style_pad_hor(pill, WINI_PAD_CARD, 0);
    lv_obj_set_style_pad_ver(pill, WINI_GAP_SM, 0);
    lv_obj_remove_flag(pill, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(pill, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_align(pill, LV_ALIGN_BOTTOM_MID, 0, -(WINI_FOOTER_H + WINI_GAP));

    lv_obj_t *lbl = lv_label_create(pill);
    lv_obj_set_style_text_font(lbl, wini_font_body(), 0);
    lv_obj_set_style_text_color(lbl, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(lbl, msg ? msg : "");

    lv_obj_set_style_opa(pill, LV_OPA_COVER, 0);
    lv_obj_fade_out(pill, TOAST_OUT, TOAST_IN + TOAST_HOLD);
    lv_obj_delete_delayed(pill, TOAST_IN + TOAST_HOLD + TOAST_OUT);
    return pill;
}
