/* alpha_screens — see alpha_screens.h.
 *
 * Layout is the §9 stack, built once and kept alive:
 *
 *     +------------------------------+  status   (robot state, muted)
 *     |                              |
 *     |        content area          |  rebuilt per stage
 *     |                              |
 *     +------------------------------+  instruction (34 px, one sentence)
 *     +------------------------------+  action   (buttons, usually empty)
 *
 * Only the content area is torn down and refilled between stages. It holds a
 * handful of objects, so lv_obj_clean() is cheap and keeps each stage's build
 * function completely independent — the tutor UI's persistent-screen rule exists
 * to protect scroll position and long-lived animations, and neither applies here.
 */
#include "screens/alpha_screens.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "theme/alpha_theme.h"
#include "ipc.h"

#define LINE_MAX 1024
#define PATH_MAX_S 320

/* Content-area artwork sizes. Chosen against the real 600x1024 panel: the
 * content band is ~620 px tall, and the robot and the food must not overlap at
 * rest or there is nothing to drag. */
#define ALPHA_ROBOT_PX 360
#define ALPHA_FOOD_PX  180
#define ALPHA_OBJECT_PX 320   /* association stage */
#define ALPHA_SMALL_PX  150   /* the "small apple" on the completion screen */
/* How far outside the robot's box the food's centre may sit and still count.
 *
 * Measured on the panel: the robot occupies y 140..499 and the food rests at
 * y≈681, so the centre must climb ~180 px to land on the face. Slop is only
 * forgiveness for an imprecise finger — at 70 px it was letting a drag that
 * covered barely a third of that distance count as feeding, which made the
 * activity trigger almost by accident. 20 px keeps it honest and still tolerant. */
#define ALPHA_DROP_SLOP  20

static lv_obj_t *s_root, *s_status, *s_status_lbl, *s_content, *s_instr, *s_action;
static int s_quit = 0;

/* The instruction can arrive as native text (English) OR as a pre-rendered image
 * (Kannada, which LVGL cannot shape). Both live in the instruction slot; exactly
 * one is visible at a time. */
static lv_obj_t *s_instr_img;

/* The language chosen on the splash toggle, sent with the begin event and then
 * fixed for the session. English until the child picks otherwise. */
static char s_lang[8] = "en";
static char s_kn_label_img[320] = "";     /* pre-rendered "ಕನ್ನಡ", from ready */
static lv_obj_t *s_lang_card_en, *s_lang_card_kn;

/* The letter the touch board is currently asking for — the tap handler needs it,
 * and it is the only piece of lesson state the UI keeps. */
static char s_target[8] = "";

void alpha_ui_request_quit(void) { s_quit = 1; }
int  alpha_ui_should_quit(void)  { return s_quit; }

/* ---- tiny flat-JSON scanners (no allocator, no nesting) -------------------- */
/* Same shape as wini_ui/app/app_state.c — the brain speaks flat objects only. */

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
        if (*p == '\\' && p[1]) p++;      /* take the escaped char literally */
        out[n++] = *p++;
    }
    out[n] = '\0';
    return 1;
}

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

/* ---- images --------------------------------------------------------------- */

/* LVGL reaches the filesystem through a drive letter; lv_conf.h maps POSIX to
 * 'A', so every absolute path from the brain becomes "A:/home/...". */
static lv_obj_t *make_img(lv_obj_t *parent, const char *abs_path)
{
    char src[PATH_MAX_S + 4];
    snprintf(src, sizeof(src), "A:%s", abs_path);
    lv_obj_t *img = lv_image_create(parent);
    lv_image_set_src(img, src);
    return img;
}

/* An image scaled to an exact `side` x `side` box.
 *
 * lv_image_set_scale() alone is a trap: it scales what is DRAWN but leaves the
 * object's box at the source size, so a 420 px asset shown at 0.6x still
 * occupies 420 px for layout and hit-testing. Aligning such an image to the
 * bottom of a container floats it ~130 px high, and a drag aimed at what you
 * can see misses the object entirely. Sizing the object and letting LVGL fit
 * the bitmap into it keeps geometry, layout and touch in agreement. */
static lv_obj_t *make_img_sized(lv_obj_t *parent, const char *abs_path, int side)
{
    lv_obj_t *img = make_img(parent, abs_path);
    lv_obj_set_size(img, side, side);
    lv_image_set_inner_align(img, LV_IMAGE_ALIGN_STRETCH);   /* art is square */
    return img;
}

/* ---- chrome --------------------------------------------------------------- */

static void set_status(const char *text)
{
    lv_label_set_text(s_status_lbl, text ? text : "");
}

/* Show the instruction as text (English) or as an image (Kannada), never both. */
static void set_instruction(const char *text, const char *text_img)
{
    if (text_img && text_img[0]) {
        char src[PATH_MAX_S + 4];
        snprintf(src, sizeof(src), "A:%s", text_img);
        lv_image_set_src(s_instr_img, src);
        lv_obj_add_flag(s_instr, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_instr_img, LV_OBJ_FLAG_HIDDEN);
        alpha_fade_in(s_instr_img, 260);
    } else {
        lv_obj_add_flag(s_instr_img, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(s_instr, text ? text : "");
        lv_obj_remove_flag(s_instr, LV_OBJ_FLAG_HIDDEN);
        alpha_fade_in(s_instr, 260);
    }
}

static void clear_action(void)
{
    lv_obj_clean(s_action);
}

static lv_obj_t *reset_content(void)
{
    lv_obj_clean(s_content);
    clear_action();
    return s_content;
}

static void close_cb(lv_event_t *e)
{
    (void)e;
    alpha_ui_request_quit();
}

/* Release a strdup'd user_data when its object is deleted. Every stage change
 * calls lv_obj_clean() on the content area, so without this the touch tiles
 * would leak one small allocation per board for the whole session. */
static void free_user_data_cb(lv_event_t *e)
{
    lv_obj_t *obj = lv_event_get_target(e);
    void *p = lv_obj_get_user_data(obj);
    if (p) {
        lv_obj_set_user_data(obj, NULL);
        free(p);
    }
}

/* A calm pill button (§9: >=72 px target, 20 px radius, 32 px label). */
static lv_obj_t *make_button(lv_obj_t *parent, const char *label,
                             lv_event_cb_t cb, bool primary)
{
    lv_obj_t *btn = lv_button_create(parent);
    lv_obj_set_size(btn, LV_SIZE_CONTENT, ALPHA_TOUCH_MIN);
    lv_obj_set_style_min_width(btn, 200, 0);
    lv_obj_set_style_radius(btn, ALPHA_RADIUS, 0);
    lv_obj_set_style_bg_color(btn,
        alpha_color(primary ? ALPHA_ACCENT : ALPHA_CARD), 0);
    lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(btn, alpha_color(ALPHA_DIVIDER), 0);
    lv_obj_set_style_border_width(btn, 2, 0);
    lv_obj_set_style_shadow_width(btn, 0, 0);
    lv_obj_set_style_pad_hor(btn, 36, 0);

    lv_obj_t *l = lv_label_create(btn);
    lv_label_set_text(l, label);
    lv_obj_set_style_text_font(l, &alpha_font_32, 0);
    lv_obj_set_style_text_color(l, alpha_color(ALPHA_TEXT), 0);
    lv_obj_center(l);

    if (cb) lv_obj_add_event_cb(btn, cb, LV_EVENT_CLICKED, NULL);
    return btn;
}

/* ---- stage: splash -------------------------------------------------------- */

static void begin_cb(lv_event_t *e)
{
    (void)e;
    set_status("Starting");
    /* letter NULL = resume where this language left off; s_lang is the toggle. */
    ipc_send_begin(NULL, s_lang);
}

/* The two language cards, highlighted to show which is selected. Green fill +
 * a slightly heavier border marks the choice — no checkmark, no color-coded
 * "right" (§2.1); it is just where the finger last landed. */
static void refresh_lang_selection(void)
{
    int kn = !strcmp(s_lang, "kn");
    lv_obj_set_style_bg_color(s_lang_card_en,
        alpha_color(kn ? ALPHA_CARD : ALPHA_ACCENT), 0);
    lv_obj_set_style_border_width(s_lang_card_en, kn ? 2 : 3, 0);
    lv_obj_set_style_bg_color(s_lang_card_kn,
        alpha_color(kn ? ALPHA_ACCENT : ALPHA_CARD), 0);
    lv_obj_set_style_border_width(s_lang_card_kn, kn ? 3 : 2, 0);
}

static void lang_en_cb(lv_event_t *e)
{ (void)e; snprintf(s_lang, sizeof(s_lang), "en"); refresh_lang_selection(); }

static void lang_kn_cb(lv_event_t *e)
{ (void)e; snprintf(s_lang, sizeof(s_lang), "kn"); refresh_lang_selection(); }

/* A language card carries a Latin label (English) or a pre-rendered script image
 * (ಕನ್ನಡ), since LVGL can't draw the akshara. */
static lv_obj_t *make_lang_card(lv_obj_t *parent, const char *text,
                                const char *img_path, lv_event_cb_t cb)
{
    lv_obj_t *card = lv_button_create(parent);
    lv_obj_set_size(card, 210, 100);
    lv_obj_set_style_radius(card, ALPHA_RADIUS, 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(card, alpha_color(ALPHA_DIVIDER), 0);
    lv_obj_set_style_shadow_width(card, 0, 0);

    if (img_path && img_path[0]) {
        lv_obj_t *g = make_img(card, img_path);
        lv_obj_center(g);
    } else {
        lv_obj_t *l = lv_label_create(card);
        lv_label_set_text(l, text);
        lv_obj_set_style_text_font(l, &alpha_font_32, 0);
        lv_obj_set_style_text_color(l, alpha_color(ALPHA_TEXT), 0);
        lv_obj_center(l);
    }
    if (cb) lv_obj_add_event_cb(card, cb, LV_EVENT_CLICKED, NULL);
    return card;
}

static void show_splash(void)
{
    lv_obj_t *c = reset_content();

    lv_obj_t *title = lv_label_create(c);
    lv_label_set_text(title, "Wini");
    lv_obj_set_style_text_font(title, &alpha_font_34, 0);
    lv_obj_set_style_text_color(title, alpha_color(ALPHA_TEXT_MUTED), 0);
    lv_obj_align(title, LV_ALIGN_CENTER, 0, -150);

    lv_obj_t *sub = lv_label_create(c);
    lv_label_set_text(sub, "Let's meet some letters");
    lv_obj_set_style_text_font(sub, &alpha_font_34, 0);
    lv_obj_align(sub, LV_ALIGN_CENTER, 0, -90);

    lv_obj_t *row = lv_obj_create(c);
    lv_obj_remove_style_all(row);
    lv_obj_set_size(row, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(row, ALPHA_GAP, 0);
    lv_obj_remove_flag(row, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_align(row, LV_ALIGN_CENTER, 0, 30);

    s_lang_card_en = make_lang_card(row, "English", NULL, lang_en_cb);
    s_lang_card_kn = make_lang_card(row, "Kannada", s_kn_label_img, lang_kn_cb);
    refresh_lang_selection();

    alpha_fade_in(c, ALPHA_ANIM_MS);
    set_instruction("", NULL);
    make_button(s_action, "Start", begin_cb, true);
}

/* ---- stage: a single big letter (intro / listen / repeat) ------------------ */

static void show_letter(const char *img_path)
{
    lv_obj_t *c = reset_content();
    if (img_path && img_path[0]) {
        lv_obj_t *img = make_img(c, img_path);
        lv_obj_center(img);
    }
    alpha_fade_in(c, ALPHA_ANIM_MS);
}

/* ---- stage: touch --------------------------------------------------------- */

static void tile_cb(lv_event_t *e)
{
    lv_obj_t *tile = lv_event_get_target(e);
    const char *letter = (const char *)lv_obj_get_user_data(tile);
    if (!letter) return;

    /* Acknowledge the tap locally so it feels instant, then let the brain
     * decide what it meant — the brain is the only thing that knows the answer,
     * and it replies with a feedback command either way. */
    if (!strcmp(letter, s_target)) alpha_pulse(tile);
    ipc_send_touch(letter);
}

/* Walk "choices":[{"letter":"A","img":"..."},...] and build a 2x2 board. */
static void show_touch(const char *line)
{
    lv_obj_t *c = reset_content();

    lv_obj_t *grid = lv_obj_create(c);
    lv_obj_remove_style_all(grid);
    lv_obj_set_size(grid, LV_PCT(100), LV_PCT(100));
    lv_obj_set_flex_flow(grid, LV_FLEX_FLOW_ROW_WRAP);
    lv_obj_set_flex_align(grid, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(grid, ALPHA_GAP, 0);
    lv_obj_set_style_pad_column(grid, ALPHA_GAP, 0);
    lv_obj_remove_flag(grid, LV_OBJ_FLAG_SCROLLABLE);

    const char *p = strstr(line, "\"choices\"");
    if (!p) return;

    while ((p = strchr(p, '{')) != NULL) {
        const char *end = strchr(p, '}');
        if (!end) break;

        char item[PATH_MAX_S + 64];
        size_t n = (size_t)(end - p + 1);
        if (n >= sizeof(item)) n = sizeof(item) - 1;
        memcpy(item, p, n);
        item[n] = '\0';

        char letter[8] = "", img[PATH_MAX_S] = "";
        if (jstr(item, "letter", letter, sizeof(letter)) &&
            jstr(item, "img", img, sizeof(img))) {

            lv_obj_t *tile = lv_obj_create(grid);
            lv_obj_remove_style_all(tile);
            lv_obj_add_style(tile, &alpha_style_card, 0);
            lv_obj_set_size(tile, 220, 220);          /* well over the 72 px min */
            lv_obj_remove_flag(tile, LV_OBJ_FLAG_SCROLLABLE);
            lv_obj_add_flag(tile, LV_OBJ_FLAG_CLICKABLE);

            /* strdup: the tile outlives this stack frame, and the letter is what
             * the tap handler reports back to the brain. Freed by lv_obj_clean()
             * via the delete hook below. */
            char *owned = strdup(letter);
            lv_obj_set_user_data(tile, owned);
            lv_obj_add_event_cb(tile, tile_cb, LV_EVENT_CLICKED, NULL);
            lv_obj_add_event_cb(tile, free_user_data_cb, LV_EVENT_DELETE, NULL);

            lv_obj_t *g = make_img(tile, img);
            lv_obj_center(g);
        }
        p = end + 1;
    }
    alpha_fade_in(c, ALPHA_ANIM_MS);
}

/* ---- stage: object association -------------------------------------------- */

static void show_assoc(const char *img_path, const char *word,
                       const char *word_img)
{
    lv_obj_t *c = reset_content();

    lv_obj_t *box = lv_obj_create(c);
    lv_obj_remove_style_all(box);
    lv_obj_set_size(box, LV_PCT(100), LV_PCT(100));
    lv_obj_set_flex_flow(box, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(box, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(box, ALPHA_GAP, 0);
    lv_obj_remove_flag(box, LV_OBJ_FLAG_SCROLLABLE);

    if (img_path && img_path[0]) make_img_sized(box, img_path, ALPHA_OBJECT_PX);

    /* The word is an image for Kannada (shaped by the brain) and native text for
     * English. */
    if (word_img && word_img[0]) {
        make_img(box, word_img);
    } else if (word && word[0]) {
        lv_obj_t *l = lv_label_create(box);
        lv_label_set_text(l, word);
        lv_obj_set_style_text_font(l, &alpha_font_34, 0);
        lv_obj_set_style_text_color(l, alpha_color(ALPHA_TEXT), 0);
    }
    alpha_fade_in(c, ALPHA_ANIM_MS);
}

/* ---- stage: feed activity -------------------------------------------------- */

static lv_obj_t *s_robot, *s_food;
static char s_robot_happy[PATH_MAX_S];
static int  s_fed_sent;
static int  s_food_grabbed;   /* has the food's resting place been recorded? */

/* Where the finger grabbed the object, as an offset from its top-left corner,
 * and where the object rests when it is not being carried. */
static lv_point_t s_grab;
static lv_point_t s_food_home;

static void set_x_cb(void *o, int32_t v) { lv_obj_set_x((lv_obj_t *)o, v); }
static void set_y_cb(void *o, int32_t v) { lv_obj_set_y((lv_obj_t *)o, v); }

static void food_drag_cb(lv_event_t *e)
{
    lv_obj_t *obj = lv_event_get_target(e);
    lv_event_code_t code = lv_event_get_code(e);
    lv_indev_t *indev = lv_indev_active();

    if (code == LV_EVENT_PRESSED) {
        /* Break the container alignment, keeping the object exactly where it
         * already is. lv_obj_align() is not a one-shot move: LVGL re-applies it
         * on every layout pass, so lv_obj_set_pos() below would be silently
         * undone and the object would never leave its slot — the drag looked
         * dead on the panel for precisely this reason. */
        lv_obj_update_layout(obj);
        int32_t x = lv_obj_get_x(obj), y = lv_obj_get_y(obj);
        lv_obj_set_align(obj, LV_ALIGN_TOP_LEFT);
        lv_obj_set_pos(obj, x, y);
        /* Captured on the FIRST press only: after a missed drop the object
         * animates back here, and re-recording it mid-gesture would make "home"
         * drift to wherever the last attempt ended. */
        if (!s_food_grabbed) {
            s_food_home.x = x;
            s_food_home.y = y;
            s_food_grabbed = 1;
        }

        /* Remember where inside the object the finger landed, so the artwork
         * stays put under the fingertip instead of jumping its centre there. */
        s_grab.x = s_grab.y = 0;
        if (indev) {
            lv_point_t p;
            lv_area_t a;
            lv_indev_get_point(indev, &p);
            lv_obj_get_coords(obj, &a);
            s_grab.x = p.x - a.x1;
            s_grab.y = p.y - a.y1;
        }
        return;
    }

    if (code == LV_EVENT_PRESSING) {
        if (!indev) return;
        /* Follow the ABSOLUTE pointer position rather than accumulating
         * lv_indev_get_vect() deltas. A finger is not a mouse: touch reports
         * absolute positions, X11 coalesces fast motion, and LVGL polls at
         * ~30 Hz — so summing per-frame deltas drops movement and drifts, and
         * the object lags behind or stops following entirely. Re-deriving the
         * position from the pointer every frame is self-correcting: any error
         * is erased on the next frame instead of accumulating. */
        lv_point_t p;
        lv_area_t a;
        lv_indev_get_point(indev, &p);
        lv_obj_get_coords(obj, &a);
        /* Nudge by the gap between where the object IS and where it SHOULD be.
         * Working in deltas of screen coords keeps this correct whatever
         * padding or border the parent has. */
        int32_t dx = (p.x - s_grab.x) - a.x1;
        int32_t dy = (p.y - s_grab.y) - a.y1;
        if (dx || dy)
            lv_obj_set_pos(obj, lv_obj_get_x(obj) + dx, lv_obj_get_y(obj) + dy);
        return;
    }

    /* PRESS_LOST as well as RELEASED: if the finger slides off the object or a
     * parent claims the gesture, no RELEASED arrives and the food would be left
     * hanging wherever the touch was lost. */
    if ((code != LV_EVENT_RELEASED && code != LV_EVENT_PRESS_LOST) ||
        s_fed_sent || !s_robot)
        return;

    /* Dropped on the robot? Compare screen-space centres — the two objects live
     * in different coordinate parents, so raw x/y would not be comparable. */
    lv_area_t fa, ra;
    lv_obj_get_coords(obj, &fa);
    lv_obj_get_coords(s_robot, &ra);
    lv_coord_t fcx = (fa.x1 + fa.x2) / 2, fcy = (fa.y1 + fa.y2) / 2;

    /* Generous catch area. A three-year-old aims approximately, and "you had it
     * but missed by 12 px" is not a lesson about the letter A. */
    if (fcx >= ra.x1 - ALPHA_DROP_SLOP && fcx <= ra.x2 + ALPHA_DROP_SLOP &&
        fcy >= ra.y1 - ALPHA_DROP_SLOP && fcy <= ra.y2 + ALPHA_DROP_SLOP) {
        s_fed_sent = 1;
        if (s_robot_happy[0]) {
            char src[PATH_MAX_S + 4];
            snprintf(src, sizeof(src), "A:%s", s_robot_happy);
            lv_image_set_src(s_robot, src);
        }
        lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);   /* eaten */
        ipc_send_fed();
        return;
    }

    printf("[alphabet_ui] drop missed: food centre (%d,%d) vs robot "
           "[%d..%d, %d..%d] slop %d\n",
           (int)fcx, (int)fcy, (int)ra.x1, (int)ra.x2, (int)ra.y1, (int)ra.y2,
           ALPHA_DROP_SLOP);
    fflush(stdout);

    /* Dropped short. Glide it back to where it started rather than leaving it
     * stranded wherever the finger let go: the child can simply try again, and
     * the screen never ends up in a state that looks broken. Movement only —
     * nothing flashes and nothing is said, because this is not a mistake. */
    lv_anim_t ax;
    lv_anim_init(&ax);
    lv_anim_set_var(&ax, obj);
    lv_anim_set_exec_cb(&ax, set_x_cb);
    lv_anim_set_values(&ax, lv_obj_get_x(obj), s_food_home.x);
    lv_anim_set_duration(&ax, ALPHA_ANIM_MS);
    lv_anim_set_path_cb(&ax, lv_anim_path_ease_in_out);
    lv_anim_start(&ax);

    lv_anim_t ay;
    lv_anim_init(&ay);
    lv_anim_set_var(&ay, obj);
    lv_anim_set_exec_cb(&ay, set_y_cb);
    lv_anim_set_values(&ay, lv_obj_get_y(obj), s_food_home.y);
    lv_anim_set_duration(&ay, ALPHA_ANIM_MS);
    lv_anim_set_path_cb(&ay, lv_anim_path_ease_in_out);
    lv_anim_start(&ay);
}

static void show_activity(const char *object_img, const char *robot_open,
                          const char *robot_happy)
{
    lv_obj_t *c = reset_content();
    s_fed_sent = 0;
    s_food_grabbed = 0;
    s_robot = s_food = NULL;
    snprintf(s_robot_happy, sizeof(s_robot_happy), "%s",
             robot_happy ? robot_happy : "");

    if (robot_open && robot_open[0]) {
        s_robot = make_img_sized(c, robot_open, ALPHA_ROBOT_PX);
        lv_obj_align(s_robot, LV_ALIGN_TOP_MID, 0, 0);
    }
    if (object_img && object_img[0]) {
        /* Small enough to sit clear of the robot's face at rest, so the child
         * has somewhere to drag FROM. */
        s_food = make_img_sized(c, object_img, ALPHA_FOOD_PX);
        lv_obj_align(s_food, LV_ALIGN_BOTTOM_MID, 0, -20);
        lv_obj_add_flag(s_food, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(s_food, food_drag_cb, LV_EVENT_PRESSED, NULL);
        lv_obj_add_event_cb(s_food, food_drag_cb, LV_EVENT_PRESSING, NULL);
        lv_obj_add_event_cb(s_food, food_drag_cb, LV_EVENT_RELEASED, NULL);
        lv_obj_add_event_cb(s_food, food_drag_cb, LV_EVENT_PRESS_LOST, NULL);
    }
    alpha_fade_in(c, ALPHA_ANIM_MS);
}

/* ---- stage: completion ----------------------------------------------------- */

static void next_cb(lv_event_t *e)  { (void)e; ipc_send_next();  }
static void again_cb(lv_event_t *e) { (void)e; ipc_send_again(); }

static void show_complete(const char *letter_img, const char *object_img)
{
    lv_obj_t *c = reset_content();

    lv_obj_t *box = lv_obj_create(c);
    lv_obj_remove_style_all(box);
    lv_obj_set_size(box, LV_PCT(100), LV_PCT(100));
    lv_obj_set_flex_flow(box, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(box, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(box, ALPHA_GAP, 0);
    lv_obj_remove_flag(box, LV_OBJ_FLAG_SCROLLABLE);

    if (letter_img && letter_img[0]) make_img(box, letter_img);
    if (object_img && object_img[0])
        make_img_sized(box, object_img, ALPHA_SMALL_PX);   /* "Small apple" §Stage 7 */

    alpha_fade_in(c, ALPHA_ANIM_MS);
    make_button(s_action, "Again", again_cb, false);
    make_button(s_action, "Next",  next_cb,  true);
}

/* ---- command applier -------------------------------------------------------- */

static void apply_stage(const char *line)
{
    char stage[24] = "", text[400] = "", letter[8] = "";
    char letter_img[PATH_MAX_S] = "", object_img[PATH_MAX_S] = "";
    char word[64] = "", robot_open[PATH_MAX_S] = "", robot_happy[PATH_MAX_S] = "";
    char text_img[PATH_MAX_S] = "", word_img[PATH_MAX_S] = "";

    jstr(line, "stage", stage, sizeof(stage));
    jstr(line, "text", text, sizeof(text));
    jstr(line, "letter", letter, sizeof(letter));
    jstr(line, "letter_img", letter_img, sizeof(letter_img));
    jstr(line, "object_img", object_img, sizeof(object_img));
    jstr(line, "word", word, sizeof(word));
    jstr(line, "robot_open", robot_open, sizeof(robot_open));
    jstr(line, "robot_happy", robot_happy, sizeof(robot_happy));
    /* Present only for non-Latin lessons: the shaped instruction / word images. */
    jstr(line, "text_img", text_img, sizeof(text_img));
    jstr(line, "word_img", word_img, sizeof(word_img));

    snprintf(s_target, sizeof(s_target), "%s", letter);

    if (!strcmp(stage, "intro") || !strcmp(stage, "listen") ||
        !strcmp(stage, "repeat")) {
        show_letter(letter_img);
    } else if (!strcmp(stage, "touch")) {
        show_touch(line);
    } else if (!strcmp(stage, "assoc")) {
        show_assoc(object_img, word, word_img);
    } else if (!strcmp(stage, "activity")) {
        show_activity(object_img, robot_open, robot_happy);
    } else if (!strcmp(stage, "complete")) {
        show_complete(letter_img, object_img);
    }

    set_instruction(text, text_img);
}

static void apply_status(const char *line)
{
    char v[24] = "";
    jstr(line, "value", v, sizeof(v));

    /* Plain words, no icons and no color changes: §2.1 rules out anything that
     * reads as a reward or an alarm. */
    if (!strcmp(v, "speaking"))       set_status("Wini is talking");
    else if (!strcmp(v, "listening")) set_status("Wini is listening");
    else if (!strcmp(v, "loading"))   set_status("Getting ready");
    else if (!strcmp(v, "error"))     set_status("Wini needs help");
    else                              set_status("");
}

static void apply_feedback(const char *line)
{
    char kind[32] = "";
    jstr(line, "kind", kind, sizeof(kind));

    /* The spoken line carries the whole message (§2.3). Nothing here flashes,
     * buzzes, or turns red — a wrong tap must leave the screen exactly as it
     * was so the child can simply look again. */
    if (!strcmp(kind, "repeat_ok") && s_content)
        alpha_pulse(s_content);
}

static void apply_line(const char *line)
{
    char cmd[24] = "";
    if (!jstr(line, "cmd", cmd, sizeof(cmd))) return;

    if (!strcmp(cmd, "stage"))         apply_stage(line);
    else if (!strcmp(cmd, "status"))   apply_status(line);
    else if (!strcmp(cmd, "feedback")) apply_feedback(line);
    else if (!strcmp(cmd, "ready")) {
        /* The pre-rendered "ಕನ್ನಡ" toggle label; captured before the splash is
         * built so the Kannada card can show it. */
        jstr(line, "kn_label_img", s_kn_label_img, sizeof(s_kn_label_img));
        show_splash();
    }
}

void alpha_ui_poll(void)
{
    char line[LINE_MAX];
    while (ipc_poll_line(line, sizeof(line))) apply_line(line);
}

/* ---- construction ----------------------------------------------------------- */

void alpha_ui_init(lv_obj_t *parent)
{
    s_root = parent;
    alpha_theme_apply_screen(s_root);
    lv_obj_set_flex_flow(s_root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(s_root, ALPHA_PAD_SCREEN, 0);
    lv_obj_set_style_pad_row(s_root, ALPHA_GAP, 0);

    /* Status strip. */
    s_status = lv_obj_create(s_root);
    lv_obj_remove_style_all(s_status);
    lv_obj_set_size(s_status, LV_PCT(100), ALPHA_STATUS_H);
    lv_obj_remove_flag(s_status, LV_OBJ_FLAG_SCROLLABLE);

    s_status_lbl = lv_label_create(s_status);
    lv_label_set_text(s_status_lbl, "");
    lv_obj_set_style_text_font(s_status_lbl, &alpha_font_22, 0);
    lv_obj_set_style_text_color(s_status_lbl, alpha_color(ALPHA_TEXT_MUTED), 0);
    lv_obj_align(s_status_lbl, LV_ALIGN_LEFT_MID, 0, 0);

    /* Close control: muted and small, in the corner. An adult needs a way out of
     * a full-screen app; a child should never notice it. */
    lv_obj_t *close = lv_button_create(s_status);
    lv_obj_set_size(close, 56, 56);
    lv_obj_align(close, LV_ALIGN_RIGHT_MID, 0, 0);
    lv_obj_set_style_radius(close, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(close, alpha_color(ALPHA_BG), 0);
    lv_obj_set_style_border_color(close, alpha_color(ALPHA_DIVIDER), 0);
    lv_obj_set_style_border_width(close, 2, 0);
    lv_obj_set_style_shadow_width(close, 0, 0);
    lv_obj_add_event_cb(close, close_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t *x = lv_label_create(close);
    lv_label_set_text(x, LV_SYMBOL_CLOSE);
    /* LV_SYMBOL_* glyphs live in Montserrat, NOT in our Nunito faces — without
     * this the label inherits the screen font and draws an empty tofu box. */
    lv_obj_set_style_text_font(x, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(x, alpha_color(ALPHA_TEXT_MUTED), 0);
    lv_obj_center(x);

    /* Content area — the only part that changes between stages. */
    s_content = lv_obj_create(s_root);
    lv_obj_remove_style_all(s_content);
    lv_obj_set_width(s_content, LV_PCT(100));
    lv_obj_set_flex_grow(s_content, 1);
    lv_obj_remove_flag(s_content, LV_OBJ_FLAG_SCROLLABLE);

    /* Instruction — exactly one sentence, always in the same place. */
    s_instr = lv_label_create(s_root);
    lv_label_set_text(s_instr, "");
    lv_label_set_long_mode(s_instr, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(s_instr, LV_PCT(100));
    lv_obj_set_style_text_font(s_instr, &alpha_font_34, 0);
    lv_obj_set_style_text_color(s_instr, alpha_color(ALPHA_TEXT), 0);
    lv_obj_set_style_text_align(s_instr, LV_TEXT_ALIGN_CENTER, 0);

    /* The image twin of the instruction, for scripts LVGL can't shape. It shares
     * the slot with s_instr; set_instruction() shows exactly one. Hidden = not
     * laid out, so the visible one always sits in the same place. */
    s_instr_img = lv_image_create(s_root);
    lv_obj_add_flag(s_instr_img, LV_OBJ_FLAG_HIDDEN);

    /* Action row. */
    s_action = lv_obj_create(s_root);
    lv_obj_remove_style_all(s_action);
    lv_obj_set_size(s_action, LV_PCT(100), ALPHA_ACTION_H);
    lv_obj_set_flex_flow(s_action, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(s_action, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(s_action, ALPHA_GAP, 0);
    lv_obj_remove_flag(s_action, LV_OBJ_FLAG_SCROLLABLE);

    show_splash();
    set_status(ipc_connected() ? "" : "Waking up");
}
