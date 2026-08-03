/* header — the fixed top band content (spec §Header).
 *
 * Always shows: Stage Indicator (chip) · Chapter / Topic (or "Question N of M")
 * · Robot Status (chip, upper-right). Built once per screen; updated via setters
 * as the session state changes.
 */
#ifndef WINI_CHROME_HEADER_H
#define WINI_CHROME_HEADER_H

#include "lvgl/lvgl.h"
#include "theme/wini_theme.h"

typedef struct wini_header wini_header_t;

/* Build the header inside a frame's header band. Owns its heap; freed with the
 * screen. */
wini_header_t *wini_header_create(lv_obj_t *band);

void wini_header_set_stage(wini_header_t *h, wini_stage_t stage);
void wini_header_set_status(wini_header_t *h, wini_status_t status);

/* Center block: line1 bold/primary, line2 muted. Pass NULL/"" for an empty line
 * (e.g. Test mode uses line1="Question 4 of 5", line2=NULL). */
void wini_header_set_lines(wini_header_t *h, const char *line1, const char *line2);

#endif /* WINI_CHROME_HEADER_H */
