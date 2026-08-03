/* screen_base — the fixed HEADER / CONTENT / FOOTER frame.
 *
 * Spec §Layout System: "Every screen must use the same layout. This layout must
 * never change. Students should always know where to look." Every screen builds
 * its widgets inside `content`; header and footer are shared chrome.
 */
#ifndef WINI_SCREEN_BASE_H
#define WINI_SCREEN_BASE_H

#include "lvgl/lvgl.h"

typedef struct {
    lv_obj_t *root;      /* the screen object (paper canvas)      */
    lv_obj_t *header;    /* fixed-height top band (see chrome/header) */
    lv_obj_t *content;   /* the middle region screens fill        */
    lv_obj_t *footer;    /* fixed-height bottom band (progress)   */
} wini_frame_t;

/* Turn `scr` into the paper canvas and lay out header/content/footer into it.
 * `out` is filled with the three regions. */
void wini_frame_create(lv_obj_t *scr, wini_frame_t *out);

#endif /* WINI_SCREEN_BASE_H */
