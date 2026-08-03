/* illustration_card — see illustration_card.h. A flat circle-with-radius figure
 * built from a bordered circle object, an lv_line radius, a center dot, and an
 * "r" label. Ink lines on paper; no fill, no shadow. */
#include "widgets/illustration_card.h"
#include "theme/wini_theme.h"

#define FIG   200   /* figure canvas (square)      */
#define DIA   176   /* circle diameter             */
#define CX    (FIG / 2)
#define CY    (FIG / 2)

/* lv_line references (does not copy) its points, so they must outlive the line:
 * the geometry is fixed, so a static const array is safe and shared. */
static const lv_point_precise_t RADIUS_PTS[] = {
    { CX, CY }, { CX + DIA / 2, CY },
};

lv_obj_t *wini_illustration_card_create(lv_obj_t *parent)
{
    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_add_style(card, &wini_style_card, 0);
    lv_obj_set_width(card, LV_PCT(100));
    lv_obj_set_height(card, LV_SIZE_CONTENT);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    /* Fixed-size transparent canvas the primitives are placed on absolutely. */
    lv_obj_t *fig = lv_obj_create(card);
    lv_obj_set_size(fig, FIG, FIG);
    lv_obj_set_style_bg_opa(fig, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(fig, 0, 0);
    lv_obj_set_style_shadow_width(fig, 0, 0);
    lv_obj_set_style_pad_all(fig, 0, 0);
    lv_obj_remove_flag(fig, LV_OBJ_FLAG_SCROLLABLE);

    /* The circle: a bordered round object, no fill (ink outline on paper). */
    lv_obj_t *circle = lv_obj_create(fig);
    lv_obj_set_size(circle, DIA, DIA);
    lv_obj_align(circle, LV_ALIGN_CENTER, 0, 0);
    lv_obj_set_style_radius(circle, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(circle, LV_OPA_TRANSP, 0);
    lv_obj_set_style_shadow_width(circle, 0, 0);
    lv_obj_set_style_border_width(circle, 2, 0);
    lv_obj_set_style_border_color(circle, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_remove_flag(circle, LV_OBJ_FLAG_SCROLLABLE);

    /* The radius line from center to the right edge. */
    lv_obj_t *radius = lv_line_create(fig);
    lv_line_set_points(radius, RADIUS_PTS, 2);
    lv_obj_set_style_line_width(radius, 2, 0);
    lv_obj_set_style_line_color(radius, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_line_rounded(radius, true, 0);

    /* Center dot. */
    lv_obj_t *dot = lv_obj_create(fig);
    lv_obj_set_size(dot, 8, 8);
    lv_obj_align(dot, LV_ALIGN_CENTER, 0, 0);
    lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(dot, wini_color(WINI_COLOR_TEXT), 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(dot, 0, 0);
    lv_obj_set_style_shadow_width(dot, 0, 0);
    lv_obj_remove_flag(dot, LV_OBJ_FLAG_SCROLLABLE);

    /* "r" label above the midpoint of the radius line. */
    lv_obj_t *r = lv_label_create(fig);
    lv_obj_set_style_text_font(r, wini_font_body(), 0);
    lv_obj_set_style_text_color(r, wini_color(WINI_COLOR_TEXT), 0);
    lv_label_set_text(r, "r");
    lv_obj_align(r, LV_ALIGN_CENTER, DIA / 4, -18);

    return card;
}
