/* status_chip — the robot-status indicator (spec §Robot Status).
 *
 * A muted matte pill with a soft dot + a state word (Listening / Thinking /
 * Teaching / Checking / Waiting / Offline). Never flashes; tint changes calmly.
 * The header shows one in its upper-right.
 */
#ifndef WINI_WIDGETS_STATUS_CHIP_H
#define WINI_WIDGETS_STATUS_CHIP_H

#include "lvgl/lvgl.h"
#include "theme/wini_theme.h"

/* Create a status chip showing `status`. Returns its root object. */
lv_obj_t *wini_status_chip_create(lv_obj_t *parent, wini_status_t status);

/* Re-tint + relabel an existing status chip. */
void wini_status_chip_set(lv_obj_t *chip, wini_status_t status);

#endif /* WINI_WIDGETS_STATUS_CHIP_H */
