/* splash — see splash.h. */
#include "screens/splash.h"
#include "screens/screen_mgr.h"
#include "theme/wini_theme.h"

#define SPLASH_HOLD_MS 1500

static void to_idle_cb(lv_timer_t *t)
{
    (void)t;
    wini_screen_show(WINI_SCREEN_IDLE);
}

lv_obj_t *wini_screen_splash_create(lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    lv_obj_set_size(root, LV_PCT(100), LV_PCT(100));
    wini_theme_apply_screen(root);
    lv_obj_set_style_border_width(root, 0, 0);
    lv_obj_set_style_radius(root, 0, 0);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_set_flex_flow(root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(root, WINI_GAP_SM, 0);

    lv_obj_t *name = lv_label_create(root);
    lv_obj_set_style_text_font(name, wini_font_heading(), 0);
    lv_obj_set_style_text_color(name, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(name, "Wini");

    lv_obj_t *sub = lv_label_create(root);
    lv_obj_set_style_text_font(sub, wini_font_body(), 0);
    lv_obj_set_style_text_color(sub, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_label_set_text(sub, "Getting ready\xe2\x80\xa6");   /* Getting ready… */

    /* One-shot auto-advance to the home screen. */
    lv_timer_t *t = lv_timer_create(to_idle_cb, SPLASH_HOLD_MS, NULL);
    lv_timer_set_repeat_count(t, 1);
    return root;
}
