/* alpha_screens — the lesson surface and the command applier.
 *
 * The brain owns the state machine (alphabet_server.py); this module owns
 * pixels. Every {"cmd":"stage",...} line rebuilds the content area for exactly
 * one stage, which is what §2.2 "One Goal Per Screen" means in practice: there
 * is never a second task on screen to be distracted by.
 */
#ifndef ALPHA_SCREENS_H
#define ALPHA_SCREENS_H

#include "lvgl/lvgl.h"

/* Build the persistent chrome (status / content / instruction / action, §9
 * Screen Layout) on `parent` and show the splash. Call after alpha_theme_init(). */
void alpha_ui_init(lv_obj_t *parent);

/* Drain the IPC queue and apply every pending command. Call once per frame from
 * the LVGL thread. */
void alpha_ui_poll(void);

/* Set by the on-screen close control; main.c's loop exits on it. */
void alpha_ui_request_quit(void);
int  alpha_ui_should_quit(void);

#endif /* ALPHA_SCREENS_H */
