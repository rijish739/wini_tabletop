/* listening — the "I'm listening" voice-state overlay (spec §Overlays).
 *
 * A calm pulsing dot over "I'm listening" / "Speak naturally." Shown while the
 * mic is open. Show/hide via wini_overlay_show / wini_overlay_hide.
 */
#ifndef WINI_OVERLAYS_LISTENING_H
#define WINI_OVERLAYS_LISTENING_H

#include "lvgl/lvgl.h"

/* Create the (hidden) listening overlay inside `parent`. Returns its root. */
lv_obj_t *wini_listening_create(lv_obj_t *parent);

#endif /* WINI_OVERLAYS_LISTENING_H */
