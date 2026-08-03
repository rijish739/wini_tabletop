"""Visual Benefit Gate (§12.1, §3.2 "visuals are earned, not default").

The single most important behavioural change in this slice. Today a tier-0 scene is armed
for ANY EXPLAIN turn purely by concept id (wini_client.client._arm_scene) — the voice is
general and the figure is a random example of the concept, which is exactly the
"canned per-concept scenes mislead" failure. This gate replaces concept-default with an
EARNED decision, computed from the learner/turn context BEFORE any modality is produced.

    decide(ctx) -> VisualIntent(visual_type, allowed, reason, asset_ref, representation_target)

A visual is allowed iff at least one §12.1 condition holds, and rejected if any override
holds. The gate does NOT invent an asset: it may only select from what upstream actually
found (an authored scene for the concept, or a pedagogy-gated crop). If a visual would
help but no supported asset exists, it returns NONE — degrade to speech, never substitute
an unrelated visual (§1.10, §3.5).

In this Phase-1+2 slice the gate only ever selects among the two visual types the device
renders today: AUTHORED_SCENE (scene_player) and RETRIEVED_CROP (display_sinks). The other
VisualType values are valid schema but need Phase-3 compilers/renderers, so the
deterministic gate does not pick them yet.
"""

from __future__ import annotations

from .contracts import ResponseContext, VisualIntent, VisualType

# concept metadata / id substrings that mark an inherently visual concept (§12.1 line 1:
# spatial / graphical / geometric / symbolic / procedural / tabular).
_VISUAL_CONCEPT_KEYWORDS = (
    "graph", "geometr", "geometric", "spatial", "diagram", "figure", "coordinate",
    "area", "volume", "derivation", "procedure", "procedural", "construction",
    "tabular", "table", "symbolic", "formula", "triangle", "circle", "polygon",
    "trigonometr", "angle", "vector", "shape", "plot", "chart", "number_line",
    "parabola", "distance", "section", "similar", "factor", "factorization",
    "equation", "quadratic", "algebra", "polynomial", "expression", "root", "zero",
)

_HIGH_LOAD = 0.7
_HIGH_FRUSTRATION = 0.6


def _is_visual_concept(ctx: ResponseContext) -> bool:
    """True if the concept itself is inherently spatial/graphical/symbolic/procedural.

    Signals: the graph concept_type/shape, the concept_id slug, and — crucially — the
    existence of an authored scene for it (someone judged it worth a visual). The scene's
    own `shape` (derivation/graph/...) rides on concept_type via the adapter."""
    hay = f"{ctx.concept_type or ''} {ctx.concept_id or ''}".lower()
    if any(k in hay for k in _VISUAL_CONCEPT_KEYWORDS):
        return True
    # An authored scene existing for this concept is itself a visual-warrant signal.
    return bool(ctx.available_scene_concept_id)


def _representation_remedy(ctx: ResponseContext) -> bool:
    """A representation gap this turn that a visual is meant to close (§12.1 lines 2/3).

    This is the ONE case that survives high cognitive load: switching to a picture when
    the learner said they cannot picture it is the remedy, not added split-attention
    (mirrors tutor_loop rule 1a-vis)."""
    return bool(
        ctx.wants_visual
        or ctx.representation_targets
        or ctx.pedagogical_action in ("REPRESENTATION_TRANSLATION", "VISUAL_ANALOGY")
    )


def decide(ctx: ResponseContext) -> VisualIntent:
    """Run the gate. Returns a VisualIntent whose ``reason`` is the telemetry cause
    (visual-usage on allow, visual-suppression on reject).

    Draw-the-answer mode: a visual is EARNED on the §12.1 pedagogical conditions alone —
    it does NOT require a pre-authored asset, because the figure is drawn from Wini's
    actual answer (response_layer.scene_author). So the gate decides earned/not-earned +
    why; the integration draws the board after generation."""
    profile = ctx.device_profile or {}
    can_render = bool(profile.get("display_present", True)) and \
        profile.get("renderer", "pillow_lvgl") not in ("", "none")

    # --- hard rejects (overrides) ---------------------------------------------------
    if not can_render:
        return VisualIntent(VisualType.NONE, False, "reject: device cannot render a visual")
    if ctx.mode == "TEST":
        return VisualIntent(VisualType.NONE, False,
                            "reject: test turn — a visual could reveal the answer")
    if ctx.response_kind.value != "instructional":
        return VisualIntent(VisualType.NONE, False,
                            f"reject: {ctx.response_kind.value} turn is speech/text only")

    remedy = _representation_remedy(ctx)
    visual_concept = _is_visual_concept(ctx)

    high_load = ctx.cognitive_load >= _HIGH_LOAD or ctx.frustration_risk >= _HIGH_FRUSTRATION
    if high_load and not remedy:
        # A decorative visual under high load adds split attention (§12.1). A
        # representation remedy is exempt — it REDUCES load by switching modality.
        return VisualIntent(VisualType.NONE, False,
                            "reject: high cognitive load — a decorative visual splits attention")

    # --- allow conditions (§12.1) ---------------------------------------------------
    allow_reason = None
    if remedy:
        allow_reason = "allow: representation gap — a picture closes it"
    elif visual_concept:
        allow_reason = "allow: concept is inherently spatial/graphical/symbolic/procedural"
    elif ctx.misconception_targets:
        allow_reason = "allow: misconception better disambiguated visually"

    if allow_reason is None:
        return VisualIntent(VisualType.NONE, False,
                            "reject: concept is better taught verbally this turn")

    # EARNED. The figure is drawn from the answer (no pre-existing asset needed) — the
    # integration authors it post-generation. Type is the drawn-scene type; asset None.
    rep_target = ctx.representation_targets[0] if ctx.representation_targets else None
    return VisualIntent(visual_type=VisualType.GENERATED_DECLARATIVE_SCENE_SPEC,
                        allowed=True, reason=allow_reason, asset_ref=None,
                        representation_target=rep_target)
