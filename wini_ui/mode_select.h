/* The Wini mode-select screen: three tappable cards — Explain / Practice /
 * Test — the device's first UI. Tapping a card sends the mode over the IPC
 * channel (ipc_send_mode). This screen carries NO face/emotions by design. */
#ifndef WINI_MODE_SELECT_H
#define WINI_MODE_SELECT_H

#include "lvgl/lvgl.h"

void mode_select_create(lv_obj_t *parent);

#endif /* WINI_MODE_SELECT_H */
