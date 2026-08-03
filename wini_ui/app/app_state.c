/* app_state — see app_state.h. */
#include "app/app_state.h"
#include "ipc.h"

#include "chrome/header.h"
#include "chrome/footer.h"
#include "widgets/question_card.h"
#include "widgets/hint_indicator.h"
#include "widgets/answer_feedback.h"
#include "widgets/explanation_card.h"
#include "widgets/result_card.h"
#include "widgets/figure_card.h"
#include "overlays/overlay_base.h"
#include "overlays/loading.h"
#include "overlays/celebration.h"
#include "overlays/thinking.h"

#include "platform/audio_fx.h"
#include "platform/brightness.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

/* ---- registry of live widgets (screens self-register) --------------------- */

typedef struct {
    wini_header_t *header;
    wini_footer_t *footer;
} chrome_ref_t;

static chrome_ref_t s_chrome[WINI_SCREEN_COUNT];

static struct {
    lv_obj_t *question, *hint, *feedback, *listening, *thinking;
} s_practice;

static struct { lv_obj_t *question; } s_test;
static struct { lv_obj_t *explanation; } s_explain;
static struct { lv_obj_t *result; } s_result;

/* Brain figure cards, one per screen that can show one (explain/practice). */
static lv_obj_t *s_figure[WINI_SCREEN_COUNT];

/* Board Buddy parent lifecycle (BOARD_BUDDY_INTEGRATION_PLAN.md §0a/§10.3). While a
 * Board Buddy pygame surface owns the 0-845 region, LVGL must NOT draw figure cards there
 * (it must not fight the visual); the pause/close controls live in the footer strip below
 * 845 and stay usable. Set on board_open, cleared on board_close. */
static int s_board_active = 0;

/* Global overlays (top layer) used when the current screen has no bound one. */
static lv_obj_t *s_loading;
static lv_obj_t *s_celebration;

void wini_app_init(void)
{
    lv_obj_t *top = lv_layer_top();
    s_loading     = wini_loading_create(top);
    s_celebration = wini_celebration_create(top);
}

void wini_app_bind_header(wini_screen_id_t id, wini_header_t *h, wini_footer_t *f)
{
    if (id < 0 || id >= WINI_SCREEN_COUNT) return;
    s_chrome[id].header = h;
    s_chrome[id].footer = f;
}

void wini_app_bind_practice(lv_obj_t *question, lv_obj_t *hint, lv_obj_t *feedback,
                            lv_obj_t *listening, lv_obj_t *thinking)
{
    s_practice.question  = question;
    s_practice.hint      = hint;
    s_practice.feedback  = feedback;
    s_practice.listening = listening;
    s_practice.thinking  = thinking;
}

void wini_app_bind_test(lv_obj_t *question)    { s_test.question = question; }
void wini_app_bind_explain(lv_obj_t *expl)     { s_explain.explanation = expl; }
void wini_app_bind_result(lv_obj_t *card)      { s_result.result = card; }

void wini_app_bind_figure(wini_screen_id_t id, lv_obj_t *card)
{
    if (id < 0 || id >= WINI_SCREEN_COUNT) return;
    s_figure[id] = card;
}

/* ---- tiny flat-JSON scanners (no allocator, no nesting) ------------------- */

/* Copy the string value of "key":"..." into out. Returns 1 if found. Handles a
 * couple of common escapes (\" and \\); other escapes pass through verbatim. */
static int jstr(const char *line, const char *key, char *out, int cap)
{
    char pat[48];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(line, pat);
    if (!p) return 0;
    p = strchr(p + strlen(pat), ':');
    if (!p) return 0;
    p++;
    while (*p == ' ' || *p == '\t') p++;
    if (*p != '"') return 0;
    p++;
    int n = 0;
    while (*p && *p != '"' && n < cap - 1) {
        if (*p == '\\' && p[1]) { p++; }   /* take the escaped char literally */
        out[n++] = *p++;
    }
    out[n] = '\0';
    return 1;
}

/* Parse the numeric/bool value of "key":N|true|false. Returns 1 if found. */
static int jint(const char *line, const char *key, int *out)
{
    char pat[48];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(line, pat);
    if (!p) return 0;
    p = strchr(p + strlen(pat), ':');
    if (!p) return 0;
    p++;
    while (*p == ' ' || *p == '\t') p++;
    if (!strncmp(p, "true", 4))  { *out = 1; return 1; }
    if (!strncmp(p, "false", 5)) { *out = 0; return 1; }
    *out = atoi(p);
    return 1;
}

/* ---- enum mapping --------------------------------------------------------- */

static int map_screen(const char *s, wini_screen_id_t *id)
{
    if (!strcasecmp(s, "idle"))     { *id = WINI_SCREEN_IDLE;     return 1; }
    if (!strcasecmp(s, "explain"))  { *id = WINI_SCREEN_EXPLAIN;  return 1; }
    if (!strcasecmp(s, "practice")) { *id = WINI_SCREEN_PRACTICE; return 1; }
    if (!strcasecmp(s, "test"))     { *id = WINI_SCREEN_TEST;     return 1; }
    if (!strcasecmp(s, "result"))   { *id = WINI_SCREEN_RESULT;   return 1; }
    if (!strcasecmp(s, "settings")) { *id = WINI_SCREEN_SETTINGS; return 1; }
    if (!strcasecmp(s, "error"))    { *id = WINI_SCREEN_ERROR;    return 1; }
    if (!strcasecmp(s, "splash"))   { *id = WINI_SCREEN_SPLASH;   return 1; }
    return 0;
}

static int map_stage(const char *s, wini_stage_t *st)
{
    if (!strcasecmp(s, "explain"))  { *st = WINI_STAGE_EXPLAIN;  return 1; }
    if (!strcasecmp(s, "practice")) { *st = WINI_STAGE_PRACTICE; return 1; }
    if (!strcasecmp(s, "test"))     { *st = WINI_STAGE_TEST;     return 1; }
    return 0;
}

static int map_status(const char *s, wini_status_t *out)
{
    if (!strcasecmp(s, "listening")) { *out = WINI_STATUS_LISTENING; return 1; }
    if (!strcasecmp(s, "thinking"))  { *out = WINI_STATUS_THINKING;  return 1; }
    if (!strcasecmp(s, "teaching"))  { *out = WINI_STATUS_TEACHING;  return 1; }
    if (!strcasecmp(s, "checking"))  { *out = WINI_STATUS_CHECKING;  return 1; }
    if (!strcasecmp(s, "waiting"))   { *out = WINI_STATUS_WAITING;   return 1; }
    if (!strcasecmp(s, "offline"))   { *out = WINI_STATUS_OFFLINE;   return 1; }
    return 0;
}

static wini_thinking_substate_t map_sub(const char *s)
{
    if (!strcasecmp(s, "understanding")) return WINI_THINKING_UNDERSTANDING;
    if (!strcasecmp(s, "searching"))     return WINI_THINKING_SEARCHING;
    if (!strcasecmp(s, "preparing"))     return WINI_THINKING_PREPARING;
    return WINI_THINKING_NONE;
}

static wini_header_t *cur_header(void)
{
    return s_chrome[wini_screen_current()].header;
}
static wini_footer_t *cur_footer(void)
{
    return s_chrome[wini_screen_current()].footer;
}
static lv_obj_t *cur_question(void)
{
    if (wini_screen_current() == WINI_SCREEN_PRACTICE) return s_practice.question;
    if (wini_screen_current() == WINI_SCREEN_TEST)     return s_test.question;
    return NULL;
}

/* ---- dispatch ------------------------------------------------------------- */

void wini_app_dispatch(const char *line)
{
    char cmd[32];
    if (!jstr(line, "cmd", cmd, sizeof(cmd))) return;

    char sv[256];
    int  iv;

    if (!strcmp(cmd, "ready")) {
        /* The client's brain-warm signal (re-sent on every UI reconnect, so a UI
         * that starts late still gets it). Only releases the splash — mid-session
         * it must not yank the student off their screen. */
        if (wini_screen_current() == WINI_SCREEN_SPLASH)
            wini_screen_show(WINI_SCREEN_IDLE);

    } else if (!strcmp(cmd, "screen")) {
        wini_screen_id_t id;
        if (jstr(line, "to", sv, sizeof(sv)) && map_screen(sv, &id))
            wini_screen_show(id);

    } else if (!strcmp(cmd, "status")) {
        wini_status_t st;
        if (jstr(line, "v", sv, sizeof(sv)) && map_status(sv, &st) && cur_header())
            wini_header_set_status(cur_header(), st);

    } else if (!strcmp(cmd, "stage")) {
        wini_stage_t stg;
        if (jstr(line, "v", sv, sizeof(sv)) && map_stage(sv, &stg) && cur_header())
            wini_header_set_stage(cur_header(), stg);

    } else if (!strcmp(cmd, "lines")) {
        char l1[128] = "", l2[128] = "";
        int has1 = jstr(line, "l1", l1, sizeof(l1));
        jstr(line, "l2", l2, sizeof(l2));
        if (has1 && cur_header())
            wini_header_set_lines(cur_header(), l1, l2[0] ? l2 : NULL);

    } else if (!strcmp(cmd, "progress")) {
        wini_stage_t stg;
        int done = 0, of = 0;
        if (jstr(line, "stage", sv, sizeof(sv)) && map_stage(sv, &stg) &&
            jint(line, "done", &done) && jint(line, "of", &of) && cur_footer())
            wini_footer_set_progress(cur_footer(), stg, done, of);

    } else if (!strcmp(cmd, "question")) {
        char n[64] = "", text[512] = "";
        jstr(line, "n", n, sizeof(n));
        if (jstr(line, "text", text, sizeof(text)) && cur_question()) {
            wini_question_card_set(cur_question(), n[0] ? n : NULL, text);
            wini_question_card_show_prompt(cur_question(), true);
            /* A fresh question invalidates the previous item's feedback banner. */
            if (s_practice.feedback)
                lv_obj_add_flag(s_practice.feedback, LV_OBJ_FLAG_HIDDEN);
        }

    } else if (!strcmp(cmd, "explain")) {
        /* Sized for a full explanation (the sink caps the body at 900 chars);
         * 256 truncated it mid-sentence even after the transport was widened. */
        char title[96] = "", body[1024] = "";
        jstr(line, "title", title, sizeof(title));
        if (jstr(line, "body", body, sizeof(body)) && s_explain.explanation) {
            wini_explanation_card_set(s_explain.explanation,
                                      title[0] ? title : NULL, body);
            if (s_board_active)
                lv_obj_add_flag(s_explain.explanation, LV_OBJ_FLAG_HIDDEN);
        }

    } else if (!strcmp(cmd, "feedback")) {
        if (jstr(line, "kind", sv, sizeof(sv)) && s_practice.feedback) {
            wini_feedback_t k = !strcasecmp(sv, "almost")
                                    ? WINI_FEEDBACK_ALMOST : WINI_FEEDBACK_CORRECT;
            wini_answer_feedback_set(s_practice.feedback, k);
            /* The banner starts hidden (no demo feedback) — show on real grades. */
            lv_obj_remove_flag(s_practice.feedback, LV_OBJ_FLAG_HIDDEN);
            if (k == WINI_FEEDBACK_CORRECT) wini_audio_cue(WINI_CUE_CORRECT);
        }

    } else if (!strcmp(cmd, "hint")) {
        if (jint(line, "level", &iv) && s_practice.hint)
            wini_hint_indicator_set(s_practice.hint, iv);

    } else if (!strcmp(cmd, "listening")) {
        lv_obj_t *ov = s_practice.listening;
        if (ov && jint(line, "on", &iv)) {
            if (iv) { wini_overlay_show(ov); wini_audio_cue(WINI_CUE_LISTEN); }
            else      wini_overlay_hide(ov);
        }

    } else if (!strcmp(cmd, "thinking")) {
        lv_obj_t *ov = s_practice.thinking;
        if (ov) {
            if (jstr(line, "sub", sv, sizeof(sv)))
                wini_thinking_set_substate(ov, map_sub(sv));
            if (jint(line, "on", &iv))
                iv ? wini_overlay_show(ov) : wini_overlay_hide(ov);
        }

    } else if (!strcmp(cmd, "loading")) {
        if (jstr(line, "text", sv, sizeof(sv)))
            wini_loading_set_text(s_loading, sv);
        if (jint(line, "on", &iv))
            iv ? wini_overlay_show(s_loading) : wini_overlay_hide(s_loading);

    } else if (!strcmp(cmd, "score")) {
        int score = 0, of = 0;
        char cap[96] = "";
        jstr(line, "caption", cap, sizeof(cap));
        if (jint(line, "score", &score) && jint(line, "of", &of) &&
            s_result.result) {
            wini_result_card_set(s_result.result, score, of, cap[0] ? cap : NULL);
            wini_screen_show(WINI_SCREEN_RESULT);
        }

    } else if (!strcmp(cmd, "celebrate")) {
        wini_celebration_play(s_celebration,
                              jstr(line, "msg", sv, sizeof(sv)) ? sv : "Well done");
        wini_audio_cue(WINI_CUE_CELEBRATE);

    } else if (!strcmp(cmd, "brightness")) {
        if (jint(line, "pct", &iv)) wini_brightness_set_percent(iv);

    } else if (!strcmp(cmd, "board_open")) {
        /* Board Buddy claims the 0-845 region as a separate surface. Clear every figure
         * card so a stale picture never shows under/around it, and gate future figures. */
        s_board_active = 1;
        for (int i = 0; i < WINI_SCREEN_COUNT; i++)
            if (s_figure[i]) wini_figure_card_clear(s_figure[i]);
        if (s_explain.explanation)
            lv_obj_add_flag(s_explain.explanation, LV_OBJ_FLAG_HIDDEN);

    } else if (!strcmp(cmd, "board_close")) {
        /* Board Buddy torn down: LVGL owns the whole panel again. */
        s_board_active = 0;
        if (s_explain.explanation)
            lv_obj_remove_flag(s_explain.explanation, LV_OBJ_FLAG_HIDDEN);

    } else if (!strcmp(cmd, "figure")) {
        if (jint(line, "off", &iv) && iv) {
            /* No figure this turn: hide on EVERY screen — a picture left from
             * a previous turn is stale wherever it is. */
            for (int i = 0; i < WINI_SCREEN_COUNT; i++)
                if (s_figure[i]) wini_figure_card_clear(s_figure[i]);
        } else if (!s_board_active) {
            /* Suppressed while Board Buddy owns the region (never fight the visual). */
            char path[288], cap[160] = "";
            jstr(line, "caption", cap, sizeof(cap));
            lv_obj_t *card = s_figure[wini_screen_current()];
            if (jstr(line, "path", path, sizeof(path)) && card)
                wini_figure_card_set(card, path, cap[0] ? cap : NULL);
        }
    }
}

void wini_app_poll(void)
{
    /* Must match ipc.c's IPC_LINE_MAX — a smaller buffer here re-truncates the
     * line the ring buffer just carried in full. */
    char line[2048];
    int guard = 0;
    while (guard++ < 32 && ipc_poll_line(line, sizeof(line)))
        wini_app_dispatch(line);
}
