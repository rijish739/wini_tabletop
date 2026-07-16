/* test — see test.h. */
#include "screens/test.h"
#include "screens/screen_mgr.h"
#include "chrome/screen_base.h"
#include "chrome/header.h"
#include "chrome/footer.h"
#include "theme/wini_theme.h"

#include "widgets/question_card.h"
#include "app/app_state.h"

lv_obj_t *wini_screen_test_create(lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    wini_frame_t f;
    wini_screen_frame(root, &f);

    /* Neutral until the brain drives it over IPC (no stale demo content). */
    wini_header_t *h = wini_header_create(f.header);
    wini_header_set_stage(h, WINI_STAGE_TEST);
    wini_header_set_lines(h, "Test", NULL);
    wini_header_set_status(h, WINI_STATUS_WAITING);

    wini_footer_t *ft = wini_footer_create(f.footer);
    wini_footer_set_progress(ft, WINI_STAGE_EXPLAIN, 0, 6);
    wini_footer_set_progress(ft, WINI_STAGE_PRACTICE, 0, 6);
    wini_footer_set_progress(ft, WINI_STAGE_TEST, 0, 6);

    lv_obj_set_flex_flow(f.content, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(f.content, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

    /* Bare question — no hint dots, no feedback, no figure. */
    lv_obj_t *qc = wini_question_card_create(f.content);
    wini_question_card_set(qc, NULL,
        "Your test question will appear here \xe2\x80\x94 just speak to begin.");
    wini_question_card_show_prompt(qc, false);

    wini_nav_button(f.content, "Finish", WINI_SCREEN_RESULT, true);

    wini_app_bind_header(WINI_SCREEN_TEST, h, ft);
    wini_app_bind_test(qc);
    return root;
}
