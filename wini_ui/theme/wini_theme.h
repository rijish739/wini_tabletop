/* wini_theme — the single source of color, type, and spacing for the whole UI.
 *
 * Design spec: a calm, matte, "paper" look (Kindle Scribe / Apple Books / NCERT
 * textbook). No gradients, no shadows, no saturated colors — everything reads as
 * if printed on paper. NOTHING elsewhere in the UI hardcodes a color or a font;
 * it all comes through here so the whole product restyles from one file.
 */
#ifndef WINI_THEME_H
#define WINI_THEME_H

#include "lvgl/lvgl.h"

/* ---- Bundled serif faces (generated from DejaVu Serif, see fonts/). -------- */
LV_FONT_DECLARE(wini_font_serif_18)   /* body    */
LV_FONT_DECLARE(wini_font_serif_28)   /* heading */

/* ---- Palette (spec §Color Palette). Muted, never fully saturated. --------- */
typedef enum {
    WINI_COLOR_BG,          /* #F6F5EF paper white   */
    WINI_COLOR_CARD,        /* card surface on paper  */
    WINI_COLOR_TEXT,        /* #222222 primary text   */
    WINI_COLOR_TEXT_MUTED,  /* #666666 secondary text */
    WINI_COLOR_DIVIDER,     /* #DAD8CF hairline        */
    WINI_COLOR_EXPLAIN,     /* #BFD8FF soft blue       */
    WINI_COLOR_PRACTICE,    /* #D7F2D2 soft green      */
    WINI_COLOR_TEST,        /* #FFE6B8 soft orange     */
    WINI_COLOR_SUCCESS,     /* #D5F4E6 soft mint       */
    WINI_COLOR_ERROR,       /* #F6D6D6 soft red        */
    WINI_COLOR_THINKING,    /* #ECE8DF warm gray       */
    WINI_COLOR_LISTENING,   /* #D9F3F5 muted cyan      */
    WINI_COLOR_COUNT
} wini_color_t;

/* ---- Stage / voice-state identifiers (used by chips, screens, FSM). ------- */
typedef enum {
    WINI_STAGE_EXPLAIN,
    WINI_STAGE_PRACTICE,
    WINI_STAGE_TEST,
} wini_stage_t;

/* Robot status chip states (spec §Robot Status). Muted colors, never flashing. */
typedef enum {
    WINI_STATUS_LISTENING,
    WINI_STATUS_THINKING,
    WINI_STATUS_TEACHING,
    WINI_STATUS_CHECKING,
    WINI_STATUS_WAITING,
    WINI_STATUS_OFFLINE,
} wini_status_t;

/* ---- Spacing / geometry tokens (px). Generous whitespace by design. ------- */
#define WINI_PAD_SCREEN   24
#define WINI_PAD_CARD      20
#define WINI_GAP           16
#define WINI_GAP_SM         8
#define WINI_RADIUS_CARD   18
#define WINI_RADIUS_CHIP   16
#define WINI_HEADER_H      96
#define WINI_FOOTER_H     104
#define WINI_TOUCH_MIN     48   /* min touch target (spec §Accessibility) */

/* ---- API ------------------------------------------------------------------ */

/* Register shared styles. Call once after lv_init(), before building screens. */
void wini_theme_init(void);

lv_color_t        wini_color(wini_color_t c);
const lv_font_t  *wini_font_heading(void);   /* 28 px serif */
const lv_font_t  *wini_font_body(void);      /* 18 px serif */

/* Tint + human label for a stage (Explain/Practice/Test). */
lv_color_t   wini_stage_color(wini_stage_t s);
const char  *wini_stage_label(wini_stage_t s);   /* "EXPLAIN" / ... */

/* Muted tint + human label for a robot status. */
lv_color_t   wini_status_color(wini_status_t s);
const char  *wini_status_label(wini_status_t s); /* "Listening" / ... */

/* Turn a screen root into the paper canvas: bg color, no scrollbars, base font
 * + text color. Every screen calls this first. */
void wini_theme_apply_screen(lv_obj_t *scr);

/* Shared matte card style (paper surface, hairline divider border, no shadow).
 * Widgets add it with lv_obj_add_style(obj, &wini_style_card, 0). */
extern lv_style_t wini_style_card;

#endif /* WINI_THEME_H */
