/* hint_indicator — see hint_indicator.h. One label of ●/○ glyphs (in the serif
 * font); the dot count is stashed in user_data so set() can rebuild the string. */
#include "widgets/hint_indicator.h"
#include "theme/wini_theme.h"

#include <stdint.h>
#include <string.h>

#define HINT_MAX_DOTS 6
#define DOT_FILLED "\xe2\x97\x8f"   /* ● U+25CF */
#define DOT_HOLLOW "\xe2\x97\x8b"   /* ○ U+25CB */
#define DOT_GAP    " "

lv_obj_t *wini_hint_indicator_create(lv_obj_t *parent, int dots)
{
    if (dots < 1) dots = 1;
    if (dots > HINT_MAX_DOTS) dots = HINT_MAX_DOTS;

    lv_obj_t *lbl = lv_label_create(parent);
    lv_obj_set_style_text_font(lbl, wini_font_body(), 0);
    lv_obj_set_style_text_color(lbl, wini_color(WINI_COLOR_TEXT_MUTED), 0);
    lv_obj_set_style_text_letter_space(lbl, 2, 0);
    lv_obj_set_user_data(lbl, (void *)(intptr_t)dots);

    wini_hint_indicator_set(lbl, 0);
    return lbl;
}

void wini_hint_indicator_set(lv_obj_t *ind, int level)
{
    int dots = (int)(intptr_t)lv_obj_get_user_data(ind);
    if (level < 0) level = 0;
    if (level > dots) level = dots;

    char buf[HINT_MAX_DOTS * (3 + 1) + 1];   /* glyph (3B) + gap per dot */
    buf[0] = '\0';
    for (int i = 0; i < dots; i++) {
        if (i) strcat(buf, DOT_GAP);
        strcat(buf, i < level ? DOT_FILLED : DOT_HOLLOW);
    }
    lv_label_set_text(ind, buf);
}
