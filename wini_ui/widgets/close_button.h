/* close_button — a small floating "Close" pill (bottom-left, above the footer).
 *
 * Tap: a confirm dialog ("Finish for now?"); confirming shuts the WHOLE package
 * down — brain, voice client and this UI — by running the package stop script
 * (WINI_STOP_CMD, default ./stop_wini_package.sh), which also resumes the
 * always-on background touch-emotion service. A stray tap from a child must not
 * end the session, hence the confirm step.
 *
 * The script kills this process too; we also request our own quit so the panel
 * clears even if the script is missing on this machine.
 */
#ifndef WINI_WIDGETS_CLOSE_BUTTON_H
#define WINI_WIDGETS_CLOSE_BUTTON_H

#include "lvgl/lvgl.h"

/* Create the floating close pill on `parent` (normally lv_layer_top()). */
lv_obj_t *wini_close_button_create(lv_obj_t *parent);

/* Ask the main loop to exit (implemented in main.c — same flag the SIGTERM
 * handler sets, so shutdown takes one path). */
void wini_ui_request_quit(void);

#endif /* WINI_WIDGETS_CLOSE_BUTTON_H */
