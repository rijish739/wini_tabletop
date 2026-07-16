/* result — see result.h. */
#include "screens/result.h"
#include "screens/screen_mgr.h"
#include "chrome/screen_base.h"
#include "chrome/header.h"
#include "chrome/footer.h"
#include "theme/wini_theme.h"

#include "widgets/result_card.h"
#include "app/app_state.h"

lv_obj_t *wini_screen_result_create(lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    wini_frame_t f;
    wini_screen_frame(root, &f);

    wini_header_t *h = wini_header_create(f.header);
    wini_header_set_stage(h, WINI_STAGE_TEST);
    wini_header_set_lines(h, "Chapter 4", "Area of a Circle");
    wini_header_set_status(h, WINI_STATUS_WAITING);

    wini_footer_t *ft = wini_footer_create(f.footer);
    wini_footer_set_progress(ft, WINI_STAGE_EXPLAIN, 6, 6);
    wini_footer_set_progress(ft, WINI_STAGE_PRACTICE, 6, 6);
    wini_footer_set_progress(ft, WINI_STAGE_TEST, 6, 6);

    /* Centered: the score is the whole screen. */
    lv_obj_set_flex_flow(f.content, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(f.content, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    lv_obj_t *rc = wini_result_card_create(f.content);
    wini_result_card_set(rc, 4, 5, "Chapter complete");

    wini_nav_button(f.content, "Back home", WINI_SCREEN_IDLE, true);

    wini_app_bind_header(WINI_SCREEN_RESULT, h, ft);
    wini_app_bind_result(rc);
    return root;
}
