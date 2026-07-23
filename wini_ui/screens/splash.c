/* splash — see splash.h. */
#include "screens/splash.h"
#include "screens/screen_mgr.h"
#include "theme/wini_theme.h"

/* The splash does NOT auto-advance: it holds until the voice client reports the
 * brain is warm ({"cmd":"ready"} -> app_state -> wini_screen_show(IDLE)). A
 * picker that is tappable before the brain answers is worse than a wait — that
 * was the "the icon doesn't start everything" complaint. The launcher normally
 * defers wini_ui until /health is ready, so this is usually a blink; the timer
 * below only exists so a brain that never warms says so instead of sitting on
 * "Getting ready…" forever. */
#define SPLASH_TICK_MS   15000
#define SPLASH_SLOW_MS   20000    /* reassure */
#define SPLASH_STUCK_MS  90000    /* admit failure */

static void wait_tick_cb(lv_timer_t *t)
{
    lv_obj_t *sub = (lv_obj_t *)lv_timer_get_user_data(t);
    if (wini_screen_current() != WINI_SCREEN_SPLASH) {   /* ready — we're done */
        lv_timer_delete(t);
        return;
    }
    static uint32_t waited = 0;
    waited += SPLASH_TICK_MS;
    if (waited >= SPLASH_STUCK_MS) {
        lv_label_set_text(sub, "Wini can't wake up. Please restart.");
        lv_timer_delete(t);
    } else if (waited >= SPLASH_SLOW_MS) {
        lv_label_set_text(sub, "Almost there\xe2\x80\xa6");
    }
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

    lv_timer_create(wait_tick_cb, SPLASH_TICK_MS, sub);
    return root;
}
