/* screen_mgr — the persistent-screen switchboard (spec §Layout / §Navigation).
 *
 * Every screen is built ONCE at init and kept alive for the whole session; the
 * manager just crossfades opacity between them (never destroy/rebuild — that
 * would drop scroll position, animations, and cost a relayout). Transitions are
 * calm: a 220 ms opacity crossfade using an explicit lv_anim on LV_STYLE_OPA —
 * NOT lv_obj_fade_* / lv_screen_load_anim, which leave objects at opa 0 in this
 * SDL/LVGL build (see overlays/overlay_base.c, widgets/toast.c). No slide/zoom.
 */
#ifndef WINI_SCREENS_SCREEN_MGR_H
#define WINI_SCREENS_SCREEN_MGR_H

#include "lvgl/lvgl.h"
#include "theme/wini_theme.h"
#include "chrome/screen_base.h"

typedef enum {
    WINI_SCREEN_SPLASH,
    WINI_SCREEN_IDLE,
    WINI_SCREEN_EXPLAIN,
    WINI_SCREEN_PRACTICE,
    WINI_SCREEN_TEST,
    WINI_SCREEN_RESULT,
    WINI_SCREEN_SETTINGS,
    WINI_SCREEN_ERROR,
    WINI_SCREEN_COUNT
} wini_screen_id_t;

/* Build every screen as a hidden full-size child of `parent` (usually the active
 * LVGL screen) and show the splash. Call once after wini_theme_init(). */
void wini_screen_mgr_init(lv_obj_t *parent);

/* Crossfade to a screen (no-op if already current). */
void wini_screen_show(wini_screen_id_t id);

wini_screen_id_t  wini_screen_current(void);
lv_obj_t         *wini_screen_root(wini_screen_id_t id);

/* ---- Shared building blocks for screen files ------------------------------ */

/* A calm matte pill button that crossfades to `target` when tapped. `primary`
 * gives it a soft-mint affirmative fill; otherwise it is a plain card pill. */
lv_obj_t *wini_nav_button(lv_obj_t *parent, const char *label,
                          wini_screen_id_t target, bool primary);

/* Turn `root` into a full-size paper screen with the shared HEADER/CONTENT/
 * FOOTER frame laid out; fills `out` (see chrome/screen_base.h). Every framed
 * screen calls this first. */
void wini_screen_frame(lv_obj_t *root, wini_frame_t *out);

#endif /* WINI_SCREENS_SCREEN_MGR_H */
