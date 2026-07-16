/* dialog — a calm modal (spec §Dialogs).
 *
 * A soft scrim over the screen with a centered matte card: title, message, and
 * up to a couple of buttons. Matte and quiet — no shadow, no bounce. Caller owns
 * the button callbacks and closes the dialog when done.
 */
#ifndef WINI_WIDGETS_DIALOG_H
#define WINI_WIDGETS_DIALOG_H

#include "lvgl/lvgl.h"

/* Create a modal over `parent` (usually the active screen). Returns the dialog
 * root (the scrim); pass it to add_button / close. */
lv_obj_t *wini_dialog_create(lv_obj_t *parent, const char *title,
                             const char *msg);

/* Append a button. `primary` tints it with the Explain accent; otherwise it is a
 * plain matte button. `cb`/`user_data` are the caller's click handler. Returns
 * the button. */
lv_obj_t *wini_dialog_add_button(lv_obj_t *dialog, const char *label,
                                 bool primary, lv_event_cb_t cb,
                                 void *user_data);

/* Dismiss and free the dialog. */
void wini_dialog_close(lv_obj_t *dialog);

#endif /* WINI_WIDGETS_DIALOG_H */
