/* wini_theme — palette, fonts, and shared styles. See wini_theme.h. */
#include "theme/wini_theme.h"

lv_style_t wini_style_card;

static const uint32_t PALETTE[WINI_COLOR_COUNT] = {
    [WINI_COLOR_BG]         = 0xF6F5EF,
    [WINI_COLOR_CARD]       = 0xFCFBF6,
    [WINI_COLOR_TEXT]       = 0x222222,
    [WINI_COLOR_TEXT_MUTED] = 0x666666,
    [WINI_COLOR_DIVIDER]    = 0xDAD8CF,
    [WINI_COLOR_EXPLAIN]    = 0xBFD8FF,
    [WINI_COLOR_PRACTICE]   = 0xD7F2D2,
    [WINI_COLOR_TEST]       = 0xFFE6B8,
    [WINI_COLOR_SUCCESS]    = 0xD5F4E6,
    [WINI_COLOR_ERROR]      = 0xF6D6D6,
    [WINI_COLOR_THINKING]   = 0xECE8DF,
    [WINI_COLOR_LISTENING]  = 0xD9F3F5,
};

lv_color_t wini_color(wini_color_t c)
{
    if (c < 0 || c >= WINI_COLOR_COUNT) c = WINI_COLOR_TEXT;
    return lv_color_hex(PALETTE[c]);
}

const lv_font_t *wini_font_heading(void) { return &wini_font_serif_28; }
const lv_font_t *wini_font_body(void)    { return &wini_font_serif_18; }

lv_color_t wini_stage_color(wini_stage_t s)
{
    switch (s) {
        case WINI_STAGE_PRACTICE: return wini_color(WINI_COLOR_PRACTICE);
        case WINI_STAGE_TEST:     return wini_color(WINI_COLOR_TEST);
        case WINI_STAGE_EXPLAIN:
        default:                  return wini_color(WINI_COLOR_EXPLAIN);
    }
}

const char *wini_stage_label(wini_stage_t s)
{
    switch (s) {
        case WINI_STAGE_PRACTICE: return "PRACTICE";
        case WINI_STAGE_TEST:     return "TEST";
        case WINI_STAGE_EXPLAIN:
        default:                  return "EXPLAIN";
    }
}

lv_color_t wini_status_color(wini_status_t s)
{
    switch (s) {
        case WINI_STATUS_LISTENING: return wini_color(WINI_COLOR_LISTENING);
        case WINI_STATUS_THINKING:  return wini_color(WINI_COLOR_THINKING);
        case WINI_STATUS_TEACHING:  return wini_color(WINI_COLOR_EXPLAIN);
        case WINI_STATUS_CHECKING:  return wini_color(WINI_COLOR_TEST);
        case WINI_STATUS_WAITING:   return wini_color(WINI_COLOR_DIVIDER);
        case WINI_STATUS_OFFLINE:   return wini_color(WINI_COLOR_ERROR);
        default:                    return wini_color(WINI_COLOR_DIVIDER);
    }
}

const char *wini_status_label(wini_status_t s)
{
    switch (s) {
        case WINI_STATUS_LISTENING: return "Listening";
        case WINI_STATUS_THINKING:  return "Thinking";
        case WINI_STATUS_TEACHING:  return "Teaching";
        case WINI_STATUS_CHECKING:  return "Checking";
        case WINI_STATUS_WAITING:   return "Waiting";
        case WINI_STATUS_OFFLINE:   return "Offline";
        default:                    return "Waiting";
    }
}

void wini_theme_init(void)
{
    /* Matte card: paper surface, hairline divider border, generous radius, and
     * emphatically NO shadow / gradient (spec §Visual Language). */
    lv_style_init(&wini_style_card);
    lv_style_set_bg_color(&wini_style_card, wini_color(WINI_COLOR_CARD));
    lv_style_set_bg_opa(&wini_style_card, LV_OPA_COVER);
    lv_style_set_radius(&wini_style_card, WINI_RADIUS_CARD);
    lv_style_set_border_width(&wini_style_card, 1);
    lv_style_set_border_color(&wini_style_card, wini_color(WINI_COLOR_DIVIDER));
    lv_style_set_border_opa(&wini_style_card, LV_OPA_COVER);
    lv_style_set_shadow_width(&wini_style_card, 0);
    lv_style_set_pad_all(&wini_style_card, WINI_PAD_CARD);
    lv_style_set_text_color(&wini_style_card, wini_color(WINI_COLOR_TEXT));
    lv_style_set_text_font(&wini_style_card, wini_font_body());
}

void wini_theme_apply_screen(lv_obj_t *scr)
{
    lv_obj_set_style_bg_color(scr, wini_color(WINI_COLOR_BG), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(scr, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_text_font(scr, wini_font_body(), 0);
    lv_obj_set_style_border_width(scr, 0, 0);
    lv_obj_set_style_radius(scr, 0, 0);
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
}
