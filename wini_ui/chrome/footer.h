/* footer — the fixed bottom band (spec §Footer).
 *
 * Overall progress as three segmented bars: Explain / Practice / Test. Bars, not
 * percentages — "Students understand progress bars faster." Always visible.
 */
#ifndef WINI_CHROME_FOOTER_H
#define WINI_CHROME_FOOTER_H

#include "lvgl/lvgl.h"
#include "theme/wini_theme.h"

typedef struct wini_footer wini_footer_t;

wini_footer_t *wini_footer_create(lv_obj_t *band);

/* Fill `done` of `total` segments for one stage (clamped, rounded to segments). */
void wini_footer_set_progress(wini_footer_t *f, wini_stage_t stage,
                              int done, int total);

#endif /* WINI_CHROME_FOOTER_H */
