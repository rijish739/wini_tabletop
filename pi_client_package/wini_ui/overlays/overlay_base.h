/* overlay_base — the shared scaffold for voice-state overlays (spec §Overlays).
 *
 * An overlay is a full-cover paper panel that fades in over the content while the
 * robot is listening / thinking / loading / celebrating, then fades out. It is
 * created once (persistent), starts hidden, and is shown/hidden by the caller
 * (the FSM in Stage 5; buttons in the Stage 3 demo).
 *
 * Fades animate LV_STYLE_OPA with an explicit lv_anim — lv_obj_fade_in is
 * unreliable in this SDL/LVGL build (it leaves the object at opacity 0; see
 * widgets/toast.c). Calm only: fade/opacity, 200-300 ms, no zoom/bounce/shake.
 */
#ifndef WINI_OVERLAYS_OVERLAY_BASE_H
#define WINI_OVERLAYS_OVERLAY_BASE_H

#include "lvgl/lvgl.h"

/* Create a hidden full-cover paper overlay inside `parent` (usually a screen's
 * content region, or lv_layer_top). Lays its children out as a centered column;
 * build the state's message + indicator into the returned root. */
lv_obj_t *wini_overlay_base_create(lv_obj_t *parent);

/* Fade the overlay in (unhidden, opa -> cover) / out (opa -> 0, then hidden). */
void wini_overlay_show(lv_obj_t *ov);
void wini_overlay_hide(lv_obj_t *ov);

/* A soft filled circle that gently pulses its opacity forever (calm, no scaling).
 * Shared by the listening / loading indicators. */
lv_obj_t *wini_overlay_pulse_dot(lv_obj_t *parent, lv_color_t color, int size);

#endif /* WINI_OVERLAYS_OVERLAY_BASE_H */
