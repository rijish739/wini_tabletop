/* practice — see practice.h. */
#include "screens/practice.h"
#include "screens/screen_mgr.h"
#include "chrome/screen_base.h"
#include "chrome/header.h"
#include "chrome/footer.h"
#include "theme/wini_theme.h"

#include "widgets/question_card.h"
#include "widgets/hint_indicator.h"
#include "widgets/answer_feedback.h"
#include "widgets/figure_card.h"

#include "overlays/overlay_base.h"
#include "overlays/listening.h"
#include "overlays/thinking.h"

#include "app/app_state.h"

/* Dismiss the content-region listening overlay when it is tapped. */
static void dismiss_overlay_cb(lv_event_t *e)
{
    wini_overlay_hide((lv_obj_t *)lv_event_get_target(e));
}

static void speak_cb(lv_event_t *e)
{
    wini_overlay_show((lv_obj_t *)lv_event_get_user_data(e));
}

/* A calm secondary pill that runs an arbitrary callback (not a screen jump). */
static void action_button(lv_obj_t *parent, const char *label,
                          lv_event_cb_t cb, void *user_data)
{
    lv_obj_t *btn = lv_button_create(parent);
    lv_obj_set_height(btn, WINI_TOUCH_MIN);
    lv_obj_set_style_radius(btn, WINI_RADIUS_CHIP, 0);
    lv_obj_set_style_shadow_width(btn, 0, 0);
    lv_obj_set_style_bg_color(btn, wini_color(WINI_COLOR_CARD), 0);
    lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(btn, 1, 0);
    lv_obj_set_style_border_color(btn, wini_color(WINI_COLOR_DIVIDER), 0);
    lv_obj_set_style_pad_hor(btn, WINI_PAD_CARD, 0);
    lv_obj_set_style_opa(btn, LV_OPA_90, LV_STATE_PRESSED);
    lv_obj_add_event_cb(btn, cb, LV_EVENT_CLICKED, user_data);

    lv_obj_t *l = lv_label_create(btn);
    lv_obj_set_style_text_font(l, wini_font_body(), 0);
    lv_obj_set_style_text_color(l, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(l, label);
    lv_obj_center(l);
}

lv_obj_t *wini_screen_practice_create(lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    wini_frame_t f;
    wini_screen_frame(root, &f);

    /* Neutral until the brain drives it over IPC (no stale demo content). */
    wini_header_t *h = wini_header_create(f.header);
    wini_header_set_stage(h, WINI_STAGE_PRACTICE);
    wini_header_set_lines(h, "Practice", NULL);
    wini_header_set_status(h, WINI_STATUS_LISTENING);

    wini_footer_t *ft = wini_footer_create(f.footer);
    wini_footer_set_progress(ft, WINI_STAGE_EXPLAIN, 0, 6);
    wini_footer_set_progress(ft, WINI_STAGE_PRACTICE, 0, 6);
    wini_footer_set_progress(ft, WINI_STAGE_TEST, 0, 6);

    lv_obj_set_flex_flow(f.content, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(f.content, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

    lv_obj_t *qc = wini_question_card_create(f.content);
    wini_question_card_set(qc, NULL,
        "Your practice question will appear here \xe2\x80\x94 just speak to begin.");
    wini_question_card_show_prompt(qc, false);

    lv_obj_t *hi = wini_hint_indicator_create(f.content, 3);
    wini_hint_indicator_set(hi, 0);

    /* Brain figure crops arrive over IPC ({"cmd":"figure"}); starts hidden. */
    lv_obj_t *fg = wini_figure_card_create(f.content);

    /* Hidden until a real graded outcome arrives (app_state "feedback" cmd);
     * a permanent demo "Correct" banner read as feedback for the last answer. */
    lv_obj_t *fb = wini_answer_feedback_create(f.content);
    lv_obj_add_flag(fb, LV_OBJ_FLAG_HIDDEN);

    wini_nav_button(f.content, "Take the test", WINI_SCREEN_TEST, true);

    /* Voice-state overlays live on the CONTENT region: they cover the question
     * but leave the header (stage/status) and footer (progress) visible. */
    lv_obj_t *ov = wini_listening_create(f.content);
    lv_obj_add_event_cb(ov, dismiss_overlay_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t *think = wini_thinking_create(f.content);
    lv_obj_add_event_cb(think, dismiss_overlay_cb, LV_EVENT_CLICKED, NULL);
    action_button(f.content, "Speak my answer", speak_cb, ov);

    /* Register the live widgets so the FSM (app_state) can drive this screen. */
    wini_app_bind_header(WINI_SCREEN_PRACTICE, h, ft);
    wini_app_bind_practice(qc, hi, fb, ov, think);
    wini_app_bind_figure(WINI_SCREEN_PRACTICE, fg);
    return root;
}
