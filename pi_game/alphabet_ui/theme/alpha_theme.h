/* alpha_theme — the only place the alphabet module names a color or a font.
 *
 * Implements pigame.md §9 (UI Design Specification) and §10 (Animation
 * Principles). The palette is deliberately desaturated: §9 forbids pure red,
 * pure green and neon, because "correct" and "wrong" must never be signalled by
 * color. Nothing in screens/ hardcodes a color — restyle the product from here.
 */
#ifndef ALPHA_THEME_H
#define ALPHA_THEME_H

#include "lvgl/lvgl.h"

/* Nunito (§9 Typography), generated from the panel's system font. */
LV_FONT_DECLARE(alpha_font_34)   /* instruction, word labels — §9 "Instruction 34" */
LV_FONT_DECLARE(alpha_font_32)   /* buttons              — §9 "Buttons 32"     */
LV_FONT_DECLARE(alpha_font_22)   /* status chip                                 */

typedef enum {
    ALPHA_BG,          /* #F8F5EF warm white  */
    ALPHA_CARD,        /* tile / card surface */
    ALPHA_TEXT,        /* primary ink         */
    ALPHA_TEXT_MUTED,  /* secondary ink       */
    ALPHA_DIVIDER,
    ALPHA_PRIMARY,     /* soft blue     */
    ALPHA_ACCENT,      /* pastel green  */
    ALPHA_HIGHLIGHT,   /* muted orange  */
    ALPHA_COLOR_COUNT
} alpha_color_t;

/* Geometry (§9 Touch Targets). 72 px minimum target, 24 px spacing, 20 px radius. */
#define ALPHA_TOUCH_MIN   72
#define ALPHA_GAP         24
#define ALPHA_RADIUS      20
#define ALPHA_PAD_SCREEN  28
#define ALPHA_STATUS_H    88
#define ALPHA_ACTION_H   120

/* §10: nothing animates for longer than this, and only scale/fade/slide. */
#define ALPHA_ANIM_MS    420

void        alpha_theme_init(void);
lv_color_t  alpha_color(alpha_color_t c);

/* Turn a screen root into the warm-white page: bg, no scrollbars, base font. */
void alpha_theme_apply_screen(lv_obj_t *scr);

/* Fade `obj` in from transparent over `ms`.
 *
 * Uses an explicit lv_anim on the opacity style — NOT lv_obj_fade_in(), which
 * leaves objects stuck at opa 0 in this SDL/LVGL build (the same trap the tutor
 * UI documents in overlays/overlay_base.c). */
void alpha_fade_in(lv_obj_t *obj, uint32_t ms);

/* Grow `obj` to `scale` and settle back — the acknowledgement for a correct
 * touch (§Stage 3 "Letter enlarges"). Scale only, ease-in-out, no bounce. */
void alpha_pulse(lv_obj_t *obj);

/* A calm matte card: paper surface, hairline border, no shadow, no gradient. */
extern lv_style_t alpha_style_card;

#endif /* ALPHA_THEME_H */
