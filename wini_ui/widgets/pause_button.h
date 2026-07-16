/* pause_button — a small floating mute toggle (bottom-right, above the footer).
 *
 * Tap: the mic is muted and the brain stops running turns (the student is
 * talking to someone else); tap again to continue. The button only reports the
 * toggle to the voice client over IPC ({"event":"pause","on":0|1}) — the client
 * owns the actual mic/turn gating, so the UI stays a thin view.
 */
#ifndef WINI_WIDGETS_PAUSE_BUTTON_H
#define WINI_WIDGETS_PAUSE_BUTTON_H

#include "lvgl/lvgl.h"

/* Create the floating pause pill on `parent` (normally lv_layer_top()). */
lv_obj_t *wini_pause_button_create(lv_obj_t *parent);

#endif /* WINI_WIDGETS_PAUSE_BUTTON_H */
