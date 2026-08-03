/* stage_chip — the Explain / Practice / Test stage indicator (spec §Header).
 *
 * A tinted matte pill carrying the stage label ("EXPLAIN" / "PRACTICE" / "TEST").
 * The chip's tint is the stage color; the header shows one in its upper-left.
 */
#ifndef WINI_WIDGETS_STAGE_CHIP_H
#define WINI_WIDGETS_STAGE_CHIP_H

#include "lvgl/lvgl.h"
#include "theme/wini_theme.h"

/* Create a stage chip showing `stage`. Returns its root object. */
lv_obj_t *wini_stage_chip_create(lv_obj_t *parent, wini_stage_t stage);

/* Re-tint + relabel an existing stage chip. */
void wini_stage_chip_set(lv_obj_t *chip, wini_stage_t stage);

#endif /* WINI_WIDGETS_STAGE_CHIP_H */
