/* app_state — the event-driven layer that turns inbound IPC commands into UI
 * changes (spec §State / §Navigation). The brain (via wini_client) sends flat
 * newline-JSON commands; app_state parses each and drives the persistent screens,
 * the header/footer chrome, the cards, and the voice-state overlays.
 *
 * Screens self-register their live widgets here at build time (wini_app_bind_*),
 * so app_state can address them without owning their construction. The dispatch
 * is data-only (no LVGL work off the main thread): main.c calls wini_app_poll()
 * once per frame to drain the IPC queue.
 *
 * Inbound command vocabulary (flat JSON, one per line):
 *   {"cmd":"screen","to":"idle|explain|practice|test|result|settings|error"}
 *   {"cmd":"status","v":"listening|thinking|teaching|checking|waiting|offline"}
 *   {"cmd":"stage","v":"explain|practice|test"}
 *   {"cmd":"lines","l1":"...","l2":"..."}
 *   {"cmd":"progress","stage":"explain|practice|test","done":N,"of":M}
 *   {"cmd":"question","n":"Question 3 of 5","text":"..."}
 *   {"cmd":"explain","title":"...","body":"..."}
 *   {"cmd":"feedback","kind":"correct|almost"}
 *   {"cmd":"hint","level":N}
 *   {"cmd":"listening","on":0|1}
 *   {"cmd":"thinking","on":0|1,"sub":"understanding|searching|preparing"}
 *   {"cmd":"loading","on":0|1,"text":"..."}
 *   {"cmd":"score","score":N,"of":M,"caption":"..."}
 *   {"cmd":"celebrate","msg":"..."}
 */
#ifndef WINI_APP_APP_STATE_H
#define WINI_APP_APP_STATE_H

#include "lvgl/lvgl.h"
#include "chrome/header.h"
#include "chrome/footer.h"
#include "theme/wini_theme.h"
#include "screens/screen_mgr.h"

/* Create the global overlays (loading / celebration) on the top layer. Call once
 * after the screens are built. */
void wini_app_init(void);

/* Screens register their live widgets (any field may be NULL). */
void wini_app_bind_header(wini_screen_id_t id, wini_header_t *h, wini_footer_t *f);
void wini_app_bind_practice(lv_obj_t *question, lv_obj_t *hint, lv_obj_t *feedback,
                            lv_obj_t *listening, lv_obj_t *thinking);
void wini_app_bind_test(lv_obj_t *question);
void wini_app_bind_explain(lv_obj_t *explanation);
void wini_app_bind_result(lv_obj_t *result_card);

/* Drain and apply every queued inbound line. Call from the LVGL thread. */
void wini_app_poll(void);

/* Apply one command line (exposed for tests / local injection). */
void wini_app_dispatch(const char *line);

#endif /* WINI_APP_APP_STATE_H */
