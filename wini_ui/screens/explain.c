/* explain — see explain.h. */
#include "screens/explain.h"
#include "screens/screen_mgr.h"
#include "chrome/screen_base.h"
#include "chrome/header.h"
#include "chrome/footer.h"
#include "theme/wini_theme.h"

#include "widgets/explanation_card.h"
#include "widgets/formula_card.h"
#include "widgets/illustration_card.h"
#include "app/app_state.h"

lv_obj_t *wini_screen_explain_create(lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    wini_frame_t f;
    wini_screen_frame(root, &f);

    /* No demo content: the header/cards start neutral and are driven live by
     * the brain over IPC ("lines"/"explain") — stale placeholder chapter titles
     * were read as real content (UI/brain desync bug, 2026-07-16). */
    wini_header_t *h = wini_header_create(f.header);
    wini_header_set_stage(h, WINI_STAGE_EXPLAIN);
    wini_header_set_lines(h, "Ask me anything", NULL);
    wini_header_set_status(h, WINI_STATUS_LISTENING);

    wini_footer_t *ft = wini_footer_create(f.footer);
    wini_footer_set_progress(ft, WINI_STAGE_EXPLAIN, 0, 6);
    wini_footer_set_progress(ft, WINI_STAGE_PRACTICE, 0, 6);
    wini_footer_set_progress(ft, WINI_STAGE_TEST, 0, 6);

    /* Content stacks vertically and may scroll if the figure runs long. */
    lv_obj_set_flex_flow(f.content, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(f.content, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    lv_obj_add_flag(f.content, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(f.content, LV_DIR_VER);

    lv_obj_t *ec = wini_explanation_card_create(f.content);
    wini_explanation_card_set(ec, NULL,
        "I'm listening \xe2\x80\x94 ask me a question to begin.");

    /* The formula/illustration cards have no IPC command yet: keep them hidden
     * so they can never show content the brain didn't send. */
    lv_obj_t *fc = wini_formula_card_create(f.content);
    lv_obj_add_flag(fc, LV_OBJ_FLAG_HIDDEN);

    lv_obj_t *ic = wini_illustration_card_create(f.content);
    lv_obj_add_flag(ic, LV_OBJ_FLAG_HIDDEN);

    wini_nav_button(f.content, "Let\xe2\x80\x99s practice", WINI_SCREEN_PRACTICE, true);

    wini_app_bind_header(WINI_SCREEN_EXPLAIN, h, ft);
    wini_app_bind_explain(ec);
    return root;
}
