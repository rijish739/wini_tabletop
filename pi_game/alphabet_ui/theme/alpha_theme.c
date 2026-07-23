#include "theme/alpha_theme.h"

lv_style_t alpha_style_card;

/* §9 Color Palette. Every value is muted on purpose: the spec bans pure red and
 * pure green precisely so that right/wrong can never be read off a color. */
static const uint32_t PALETTE[ALPHA_COLOR_COUNT] = {
    [ALPHA_BG]         = 0xF8F5EF,   /* warm white  */
    [ALPHA_CARD]       = 0xFFFDF8,   /* card on paper */
    [ALPHA_TEXT]       = 0x3A3730,
    [ALPHA_TEXT_MUTED] = 0x7A7466,
    [ALPHA_DIVIDER]    = 0xE2DDD1,
    [ALPHA_PRIMARY]    = 0xA8C8E8,   /* soft blue     */
    [ALPHA_ACCENT]     = 0xB8DDB0,   /* pastel green  */
    [ALPHA_HIGHLIGHT]  = 0xE8B583,   /* muted orange  */
};

lv_color_t alpha_color(alpha_color_t c)
{
    if (c < 0 || c >= ALPHA_COLOR_COUNT) c = ALPHA_TEXT;
    return lv_color_hex(PALETTE[c]);
}

void alpha_theme_init(void)
{
    lv_style_init(&alpha_style_card);
    lv_style_set_bg_color(&alpha_style_card, alpha_color(ALPHA_CARD));
    lv_style_set_bg_opa(&alpha_style_card, LV_OPA_COVER);
    lv_style_set_radius(&alpha_style_card, ALPHA_RADIUS);
    lv_style_set_border_color(&alpha_style_card, alpha_color(ALPHA_DIVIDER));
    lv_style_set_border_width(&alpha_style_card, 2);
    /* No shadow and no gradient anywhere — §9's "paper", not a glossy app. */
    lv_style_set_shadow_width(&alpha_style_card, 0);
    lv_style_set_pad_all(&alpha_style_card, 0);
}

void alpha_theme_apply_screen(lv_obj_t *scr)
{
    lv_obj_set_style_bg_color(scr, alpha_color(ALPHA_BG), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(scr, alpha_color(ALPHA_TEXT), 0);
    lv_obj_set_style_text_font(scr, &alpha_font_34, 0);
    lv_obj_set_style_border_width(scr, 0, 0);
    lv_obj_set_style_pad_all(scr, 0, 0);
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
}

/* ---- Animation (§10: scale/fade/slide only, <=600 ms, ease-in-out) -------- */

static void set_opa_cb(void *obj, int32_t v)
{
    lv_obj_set_style_opa((lv_obj_t *)obj, (lv_opa_t)v, 0);
}

void alpha_fade_in(lv_obj_t *obj, uint32_t ms)
{
    if (!obj) return;
    /* Set the start value directly before animating. lv_obj_fade_in() is the
     * obvious call here and it is WRONG in this SDL/LVGL build: objects stay at
     * opa 0 and the screen silently renders blank (wini_ui hit the same thing).
     * An explicit lv_anim over the opacity style is the version that works. */
    lv_obj_set_style_opa(obj, LV_OPA_TRANSP, 0);

    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, obj);
    lv_anim_set_exec_cb(&a, set_opa_cb);
    lv_anim_set_values(&a, LV_OPA_TRANSP, LV_OPA_COVER);
    lv_anim_set_duration(&a, ms > ALPHA_ANIM_MS ? ALPHA_ANIM_MS : ms);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_in_out);
    lv_anim_start(&a);
}

static void set_zoom_cb(void *obj, int32_t v)
{
    lv_obj_set_style_transform_scale((lv_obj_t *)obj, (int32_t)v, 0);
}

void alpha_pulse(lv_obj_t *obj)
{
    if (!obj) return;
    /* 256 == 1.0x in LVGL v9 scale units. Grow to 1.18x and settle: the "letter
     * enlarges" acknowledgement from §Stage 3. playback_* gives the return leg,
     * so the object ends exactly where it started with no bounce overshoot. */
    lv_obj_set_style_transform_pivot_x(obj, lv_pct(50), 0);
    lv_obj_set_style_transform_pivot_y(obj, lv_pct(50), 0);

    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, obj);
    lv_anim_set_exec_cb(&a, set_zoom_cb);
    lv_anim_set_values(&a, 256, 302);
    lv_anim_set_duration(&a, ALPHA_ANIM_MS / 2);
    lv_anim_set_playback_duration(&a, ALPHA_ANIM_MS / 2);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_in_out);
    lv_anim_start(&a);
}
