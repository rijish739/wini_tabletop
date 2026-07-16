/* chip — the matte rounded pill primitive shared by stage_chip / status_chip.
 *
 * A tinted, shadowless, radius-16 container laid out as a centered flex row
 * (icon/dot + label). Higher-level chips add their own children and expose
 * setters. Not a spec widget on its own — a building block so no two chip
 * variants re-implement the pill styling.
 */
#ifndef WINI_WIDGETS_CHIP_H
#define WINI_WIDGETS_CHIP_H

#include "lvgl/lvgl.h"

/* A rounded, matte chip: tinted background `bg`, no shadow, content centered. */
lv_obj_t *wini_chip_create(lv_obj_t *parent, lv_color_t bg);

#endif /* WINI_WIDGETS_CHIP_H */
