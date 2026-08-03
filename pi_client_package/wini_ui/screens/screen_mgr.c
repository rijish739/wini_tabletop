/* screen_mgr — see screen_mgr.h. */
#include "screens/screen_mgr.h"
#include "chrome/screen_base.h"
#include "theme/wini_theme.h"

#include "screens/splash.h"
#include "screens/idle.h"
#include "screens/explain.h"
#include "screens/practice.h"
#include "screens/test.h"
#include "screens/result.h"
#include "screens/settings.h"
#include "screens/error.h"

#include <stdint.h>

#define WINI_SCREEN_FADE_MS 220

static lv_obj_t        *s_screen[WINI_SCREEN_COUNT];
static wini_screen_id_t s_current = WINI_SCREEN_COUNT;   /* none yet */

/* ---- opacity crossfade (explicit anim; see header rationale) -------------- */

static void opa_exec_cb(void *obj, int32_t v)
{
    lv_obj_set_style_opa((lv_obj_t *)obj, (lv_opa_t)v, 0);
}

static void fade_out_done_cb(lv_anim_t *a)
{
    lv_obj_add_flag((lv_obj_t *)a->var, LV_OBJ_FLAG_HIDDEN);
}

static void fade(lv_obj_t *s, lv_opa_t to, bool hide_when_done)
{
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, s);
    lv_anim_set_exec_cb(&a, opa_exec_cb);
    lv_anim_set_values(&a, lv_obj_get_style_opa(s, 0), to);
    lv_anim_set_duration(&a, WINI_SCREEN_FADE_MS);
    if (hide_when_done) lv_anim_set_completed_cb(&a, fade_out_done_cb);
    lv_anim_start(&a);
}

/* ---- nav button ----------------------------------------------------------- */

static void nav_btn_cb(lv_event_t *e)
{
    wini_screen_show((wini_screen_id_t)(intptr_t)lv_event_get_user_data(e));
}

lv_obj_t *wini_nav_button(lv_obj_t *parent, const char *label,
                          wini_screen_id_t target, bool primary)
{
    lv_obj_t *btn = lv_button_create(parent);
    lv_obj_set_height(btn, WINI_TOUCH_MIN);
    lv_obj_set_style_radius(btn, WINI_RADIUS_CHIP, 0);
    lv_obj_set_style_shadow_width(btn, 0, 0);
    lv_obj_set_style_bg_color(
        btn, wini_color(primary ? WINI_COLOR_SUCCESS : WINI_COLOR_CARD), 0);
    lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(btn, 1, 0);
    lv_obj_set_style_border_color(btn, wini_color(WINI_COLOR_DIVIDER), 0);
    lv_obj_set_style_pad_hor(btn, WINI_PAD_CARD, 0);
    lv_obj_set_style_opa(btn, LV_OPA_90, LV_STATE_PRESSED);   /* calm press */
    lv_obj_add_event_cb(btn, nav_btn_cb, LV_EVENT_CLICKED,
                        (void *)(intptr_t)target);

    lv_obj_t *l = lv_label_create(btn);
    lv_obj_set_style_text_font(l, wini_font_body(), 0);
    lv_obj_set_style_text_color(l, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(l, label);
    lv_obj_center(l);
    return btn;
}

/* ---- shared frame --------------------------------------------------------- */

void wini_screen_frame(lv_obj_t *root, wini_frame_t *out)
{
    lv_obj_set_size(root, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_border_width(root, 0, 0);
    lv_obj_set_style_radius(root, 0, 0);
    lv_obj_set_style_shadow_width(root, 0, 0);
    wini_frame_create(root, out);   /* paper canvas + HEADER/CONTENT/FOOTER */
}

/* ---- lifecycle ------------------------------------------------------------ */

void wini_screen_mgr_init(lv_obj_t *parent)
{
    /* The parent hosts all screens stacked at 0,0; it must not scroll or pad. */
    lv_obj_remove_flag(parent, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_all(parent, 0, 0);

    s_screen[WINI_SCREEN_SPLASH]   = wini_screen_splash_create(parent);
    s_screen[WINI_SCREEN_IDLE]     = wini_screen_idle_create(parent);
    s_screen[WINI_SCREEN_EXPLAIN]  = wini_screen_explain_create(parent);
    s_screen[WINI_SCREEN_PRACTICE] = wini_screen_practice_create(parent);
    s_screen[WINI_SCREEN_TEST]     = wini_screen_test_create(parent);
    s_screen[WINI_SCREEN_RESULT]   = wini_screen_result_create(parent);
    s_screen[WINI_SCREEN_SETTINGS] = wini_screen_settings_create(parent);
    s_screen[WINI_SCREEN_ERROR]    = wini_screen_error_create(parent);

    for (int i = 0; i < WINI_SCREEN_COUNT; i++) {
        lv_obj_set_style_opa(s_screen[i], LV_OPA_TRANSP, 0);
        lv_obj_add_flag(s_screen[i], LV_OBJ_FLAG_HIDDEN);
    }

    /* Show splash immediately (no fade on the very first frame). */
    s_current = WINI_SCREEN_SPLASH;
    lv_obj_set_style_opa(s_screen[WINI_SCREEN_SPLASH], LV_OPA_COVER, 0);
    lv_obj_remove_flag(s_screen[WINI_SCREEN_SPLASH], LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_screen[WINI_SCREEN_SPLASH]);
}

void wini_screen_show(wini_screen_id_t id)
{
    if (id < 0 || id >= WINI_SCREEN_COUNT) return;
    if (id == s_current) return;

    lv_obj_t *from = (s_current < WINI_SCREEN_COUNT) ? s_screen[s_current] : NULL;
    lv_obj_t *to   = s_screen[id];

    lv_obj_remove_flag(to, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(to);
    fade(to, LV_OPA_COVER, false);
    if (from && from != to) fade(from, LV_OPA_TRANSP, true);

    s_current = id;
}

wini_screen_id_t wini_screen_current(void) { return s_current; }

lv_obj_t *wini_screen_root(wini_screen_id_t id)
{
    return (id >= 0 && id < WINI_SCREEN_COUNT) ? s_screen[id] : NULL;
}
