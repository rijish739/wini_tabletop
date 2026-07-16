/* idle — see idle.h. Paper home launcher (replaces the legacy dark picker). */
#include "screens/idle.h"
#include "screens/screen_mgr.h"
#include "theme/wini_theme.h"
#include "ipc.h"

#include <stdint.h>

typedef struct {
    wini_stage_t      stage;
    wini_screen_id_t  target;
    const char       *mode;      /* IPC value sent to the brain (X-Wini-Mode) */
    const char       *title;
    const char       *subtitle;
} launch_def_t;

static const launch_def_t LAUNCH[] = {
    { WINI_STAGE_EXPLAIN,  WINI_SCREEN_EXPLAIN,  "EXPLAIN",  "Explain",  "Learn something new" },
    { WINI_STAGE_PRACTICE, WINI_SCREEN_PRACTICE, "PRACTICE", "Practice", "Try it together"     },
    { WINI_STAGE_TEST,     WINI_SCREEN_TEST,     "TEST",     "Test",     "Show what you know"  },
};
#define N_LAUNCH (sizeof(LAUNCH) / sizeof(LAUNCH[0]))

/* Tapping a card tells the brain which mode to run (best-effort — the UI still
 * navigates locally even if the channel is down) and opens that screen. The
 * brain then drives the turn back over the same channel (app_state). */
static void card_cb(lv_event_t *e)
{
    const launch_def_t *d = (const launch_def_t *)lv_event_get_user_data(e);
    ipc_send_mode(d->mode);
    wini_screen_show(d->target);
}

/* A soft-tinted stage card: matte, no shadow, hairline border, serif labels. */
static void launch_card(lv_obj_t *parent, const launch_def_t *d)
{
    lv_obj_t *card = lv_button_create(parent);
    lv_obj_set_width(card, LV_PCT(100));
    lv_obj_set_height(card, 168);
    lv_obj_set_style_radius(card, WINI_RADIUS_CARD, 0);
    lv_obj_set_style_shadow_width(card, 0, 0);
    lv_obj_set_style_bg_color(card, wini_stage_color(d->stage), 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(card, 1, 0);
    lv_obj_set_style_border_color(card, wini_color(WINI_COLOR_DIVIDER), 0);
    lv_obj_set_style_opa(card, LV_OPA_90, LV_STATE_PRESSED);
    lv_obj_set_style_pad_all(card, WINI_PAD_CARD, 0);
    lv_obj_add_event_cb(card, card_cb, LV_EVENT_CLICKED, (void *)d);

    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(card, WINI_GAP_SM, 0);

    lv_obj_t *ttl = lv_label_create(card);
    lv_obj_set_style_text_font(ttl, wini_font_heading(), 0);
    lv_obj_set_style_text_color(ttl, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(ttl, d->title);

    lv_obj_t *sub = lv_label_create(card);
    lv_obj_set_style_text_font(sub, wini_font_body(), 0);
    lv_obj_set_style_text_color(sub, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_label_set_text(sub, d->subtitle);
}

lv_obj_t *wini_screen_idle_create(lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    lv_obj_set_size(root, LV_PCT(100), LV_PCT(100));
    wini_theme_apply_screen(root);
    lv_obj_set_style_border_width(root, 0, 0);
    lv_obj_set_style_radius(root, 0, 0);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_set_flex_flow(root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(root, WINI_PAD_SCREEN, 0);
    lv_obj_set_style_pad_row(root, WINI_GAP, 0);

    lv_obj_t *greeting = lv_label_create(root);
    lv_obj_set_style_text_font(greeting, wini_font_heading(), 0);
    lv_obj_set_style_text_color(greeting, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_pad_top(greeting, WINI_GAP_SM, 0);
    lv_label_set_text(greeting, "What shall we do?");

    for (size_t i = 0; i < N_LAUNCH; i++)
        launch_card(root, &LAUNCH[i]);

    /* Quiet settings affordance (secondary pill). */
    wini_nav_button(root, "Settings", WINI_SCREEN_SETTINGS, false);
    return root;
}
