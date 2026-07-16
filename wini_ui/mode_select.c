/* Mode-select screen — Explain / Practice / Test, portrait 600x1024. */
#include "mode_select.h"
#include "ipc.h"

#include <stdio.h>

typedef struct {
    const char *mode;      /* protocol value sent over IPC */
    const char *symbol;    /* LVGL built-in glyph */
    const char *title;
    const char *subtitle;
    uint32_t    accent;    /* card background */
} card_def_t;

static const card_def_t CARDS[] = {
    { "EXPLAIN",  LV_SYMBOL_LIST, "Explain",  "Learn something new", 0x2563EB },
    { "PRACTICE", LV_SYMBOL_EDIT, "Practice", "Try it together",     0x16A34A },
    { "TEST",     LV_SYMBOL_OK,   "Test",     "Show what you know",  0xEA580C },
};
#define N_CARDS (sizeof(CARDS) / sizeof(CARDS[0]))

static lv_obj_t *status_label;

static void card_event_cb(lv_event_t *e)
{
    const card_def_t *c = (const card_def_t *)lv_event_get_user_data(e);
    printf("[wini_ui] tap %s\n", c->mode);
    fflush(stdout);

    int ok = ipc_send_mode(c->mode);
    if (status_label) {
        if (ok == 0)
            lv_label_set_text_fmt(status_label, "%s  Starting %s...",
                                  LV_SYMBOL_OK, c->title);
        else
            lv_label_set_text_fmt(status_label, "%s  waiting for Wini...",
                                  LV_SYMBOL_WARNING);
    }
}

void mode_select_create(lv_obj_t *parent)
{
    lv_obj_set_style_bg_color(parent, lv_color_hex(0x0D1117), 0);
    lv_obj_set_style_bg_opa(parent, LV_OPA_COVER, 0);
    lv_obj_remove_flag(parent, LV_OBJ_FLAG_SCROLLABLE);

    /* vertical stack, centered horizontally */
    lv_obj_set_flex_flow(parent, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(parent, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(parent, 24, 0);
    lv_obj_set_style_pad_row(parent, 22, 0);

    lv_obj_t *title = lv_label_create(parent);
    lv_label_set_text(title, "What shall we do?");
    lv_obj_set_style_text_color(title, lv_color_hex(0xF0F6FC), 0);
    lv_obj_set_style_text_font(title, &lv_font_montserrat_36, 0);
    lv_obj_set_style_pad_top(title, 16, 0);
    lv_obj_set_style_pad_bottom(title, 4, 0);

    for (size_t i = 0; i < N_CARDS; i++) {
        const card_def_t *c = &CARDS[i];

        lv_obj_t *card = lv_button_create(parent);
        lv_obj_set_width(card, LV_PCT(100));
        lv_obj_set_height(card, 215);
        lv_obj_set_style_bg_color(card, lv_color_hex(c->accent), 0);
        lv_obj_set_style_radius(card, 24, 0);
        lv_obj_set_style_shadow_width(card, 0, 0);
        lv_obj_set_style_opa(card, LV_OPA_70, LV_STATE_PRESSED);  /* press feedback */
        lv_obj_add_event_cb(card, card_event_cb, LV_EVENT_CLICKED, (void *)c);

        lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(card, LV_FLEX_ALIGN_CENTER,
                              LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_row(card, 6, 0);

        lv_obj_t *icon = lv_label_create(card);
        lv_label_set_text(icon, c->symbol);
        lv_obj_set_style_text_color(icon, lv_color_hex(0xFFFFFF), 0);
        lv_obj_set_style_text_font(icon, &lv_font_montserrat_48, 0);

        lv_obj_t *ttl = lv_label_create(card);
        lv_label_set_text(ttl, c->title);
        lv_obj_set_style_text_color(ttl, lv_color_hex(0xFFFFFF), 0);
        lv_obj_set_style_text_font(ttl, &lv_font_montserrat_36, 0);

        lv_obj_t *sub = lv_label_create(card);
        lv_label_set_text(sub, c->subtitle);
        lv_obj_set_style_text_color(sub, lv_color_hex(0xF0F6FC), 0);
        lv_obj_set_style_text_font(sub, &lv_font_montserrat_20, 0);
    }

    status_label = lv_label_create(parent);
    lv_label_set_text(status_label, "Tap a card to begin");
    lv_obj_set_style_text_color(status_label, lv_color_hex(0x8B949E), 0);
    lv_obj_set_style_text_font(status_label, &lv_font_montserrat_20, 0);
    lv_obj_set_style_pad_top(status_label, 6, 0);
}
