"""Generate the Gemini perception schema enums + cached static block from the
artifacts of record (Part 11 §5.4).

The enum vocabularies are read from the SHIPPED artifacts so the schema can never
silently drift from them (the CUE_NAMES/width-coupling spirit in CLAUDE.md):

    models/exemplar_classifier/label_space.json   -> signal label enum (38)
    models/concept_resolver/concepts_meta.json    -> concept id/name catalog (108)

The signal *definitions*, intent taxonomy, and few-shot anchors are authored here
(intent has no labeled data), but the definition set is asserted to cover EXACTLY
the shipped labels — an added/removed label fails the build until reconciled.

Outputs (perception/build/):
    perception_enums.json     intents, labels, concept_ids, concept_names, sentinel
    perception_context.md     the cached static block (system instruction body)
    perception_manifest.json  provenance: source files, counts, sha256

Run:  python -m perception.build_perception
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Dict, List

from .config import BUILD_DIR
from .route import INHERIT, INTENTS

ROOT = Path(__file__).resolve().parent.parent
LABEL_SPACE = ROOT / "models" / "exemplar_classifier" / "label_space.json"
CONCEPTS_META = ROOT / "models" / "concept_resolver" / "concepts_meta.json"
SPLITS = ROOT / "models" / "exemplar_classifier" / "splits.json"
CURATED = ROOT / "dataset" / "exemplar_dataset_10000_curated.json"

# --------------------------------------------------------------------------- #
# Intent taxonomy (authored, from §4.3). Only LEARNING may move learner state.
# --------------------------------------------------------------------------- #
INTENT_DEFS: Dict[str, str] = {
    "LEARNING": "About the maths itself: a maths question, an answer attempt, confusion about a "
                "concept, or a request to learn / explain / see an example / practise. This is the "
                "ONLY intent that may move learner state.",
    "SOCIAL": "Greetings, chit-chat, 'how are you', compliments, small talk — not about maths and "
              "not a feeling that needs support.",
    "META_CAPABILITY": "Asking what you are, what you can do, or how you work ('are you a robot?', "
                       "'what can you teach me?').",
    "OFF_DOMAIN_ACADEMIC": "An accurate but NON-maths factual question (geography, science trivia, "
                           "history, spelling) — answerable, but outside maths.",
    "SESSION_CONTROL": "Managing the SESSION, not the maths: stop, pause, take a break, 'I'm tired', "
                       "'I'm bored', 'bye', 'I don't want to study', 'can we do something else'.",
    "EMOTIONAL": "Expressing a feeling (sad, worried, frustrated, excited, nervous about an exam) "
                 "with NO sign of self-harm, abuse, or danger.",
    "SAFETY": "ANY sign of self-harm, wanting to die, being hurt/abused, being in danger, or wanting "
              "to hurt self or others. Flag generously — recall matters far more than precision here.",
    "NONSENSE": "Unintelligible, empty, keyboard-mash, or not language.",
}

# --------------------------------------------------------------------------- #
# Signal definitions (authored, negative boundaries per §5.5b). Validated to
# cover EXACTLY the shipped label_space.json set at build time.
# --------------------------------------------------------------------------- #
SIGNAL_DEFS: Dict[str, str] = {
    "abstraction_attempt": "Generalizes beyond the specific case, reaches for the underlying rule "
                           "('so is it always...?', 'in general'). Not a plain question.",
    "acknowledgment": "Positive confirmation they UNDERSTOOD ('yes got it', 'makes sense now', "
                      "'understood'). The OPPOSITE of confusion — never flag confusion for these.",
    "algebraic": "Engages the symbolic/algebraic form: equations, variables, manipulation.",
    "answer_attempt": "The reply actually tries to ANSWER the question asked ('i think it's 5', "
                      "'is it 0', '= 12'). Not a restatement and not a new question.",
    "anxiety": "Worry/fear about maths or an exam ('i'm scared i'll fail'). More than plain difficulty.",
    "cognitive_overload": "Explicitly too much at once ('this is too much', 'so many steps', 'my head "
                          "hurts'). Not ordinary single-point confusion.",
    "conflict": "Notices a contradiction between two ideas or results ('but earlier it was...', "
                "'that doesn't match').",
    "confusion": "Does not understand / is lost / 'what is even happening'. Do NOT flag for an "
                 "acknowledgment or a neutral request for the next step.",
    "curiosity": "Genuine interest, wants to explore ('ooh why?', 'what if', 'how does that work'). "
                 "Not frustration.",
    "diagrammatic": "Refers to or wants a diagram/figure form of the idea.",
    "disengagement": "Bored / checked out / doesn't care ('whatever', 'this is boring'). A stated "
                     "wish to STOP is SESSION_CONTROL intent, not this signal.",
    "environmental_feedback": "Refers to their physical surroundings or an external tool/app state.",
    "example_request": "Asks for a worked example or a concrete sum ('show me an example', 'with numbers').",
    "frustration": "Irritation/anger at the material or the tutor ('ugh', 'this is stupid', 'you keep "
                   "repeating'). Not calm confusion.",
    "graphical": "Engages with or asks for a graph/plot.",
    "high_confidence": "Feels it is easy / already knows it ('too easy', 'i know this'). Not a hesitant try.",
    "hint_dependency": "Leans on hints/answers rather than trying ('just tell me', 'give me the answer').",
    "low_confidence": "Self-doubt ('i'm bad at this', 'i feel dumb', 'i can't do it'). Not a neutral wrong answer.",
    "misconception_clue": "States something mathematically WRONG as if it were the rule, or "
                          "overgeneralizes ('a negative times a negative is negative', 'always...'). Probe, don't assume.",
    "physical": "Real-life / hands-on / application framing ('where is this used in real life?').",
    "prerequisite_awareness": "Recognizes a missing earlier idea ('i forgot how fractions work').",
    "prerequisite_weakness": "A weak earlier skill surfaces in the attempt (may be unstated).",
    "procedural_focus": "Focused on the steps/procedure ('what do i do first', 'which formula').",
    "question": "The utterance asks something (a '?' or a wh-/auxiliary opener).",
    "ready_for_next": "Wants to move on / finished this ('next', 'what's next', 'done with this').",
    "recurring_error": "The SAME mistake appears again after it was addressed.",
    "representation_shift": "Wants the idea in a different form (words <-> symbols <-> picture).",
    "request_hint": "Explicitly asks for a hint / where to start ('give me a hint', 'i'm stuck, how do i begin').",
    "request_representation": "Asks for a specific representation (draw it, show a picture/graph/table).",
    "self_correction": "Catches and fixes their own error ('wait, actually...', 'no, i mean').",
    "self_monitoring": "Reflects on their own understanding/strategy ('let me check', 'i get the first part but...').",
    "shortcut_seeking": "Wants a faster trick over understanding ('is there a shortcut?', 'easy way?').",
    "simplification_request": "Asks for a simpler/easier explanation ('say it simpler', 'in easy words', 'explain again').",
    "skepticism": "Doubts what the tutor said ('are you sure?', 'that can't be right').",
    "tabular": "Engages with or wants a table representation.",
    "topic_shift": "Switches to a DIFFERENT maths topic ('actually, let's do trigonometry').",
    "transfer_attempt": "Tries to apply the idea to a new/related problem ('could i use this for...?').",
    "verbal_analogy": "Uses or asks for an analogy / real-world comparison ('is it like...?').",
}

# --------------------------------------------------------------------------- #
# Few-shot anchors (authored). Balanced across intents and INCLUDING neutral /
# 'nothing detected' / inherit cases so the model learns an empty result is
# common and correct (§5.5). Concept ids are validated in-catalog by build().
# --------------------------------------------------------------------------- #
def _anchor(utt, intent, concept, signals, answer=False, also=False, safety=False, secondary=None):
    return {
        "utterance": utt,
        "perception": {
            "intent": intent,
            "also_learning": also,
            "concept_id": concept,
            "concept_confidence": 0.9 if concept != INHERIT else 0.0,
            "secondary_concepts": secondary or [],
            "signal_scores": signals,
            "answer_attempt": answer,
            "safety": safety,
        },
    }


FEWSHOT_ANCHORS = [
    _anchor("i don't understand why the parabola opens upward, can you draw it",
            "LEARNING", "jemh102__quadratic_zero_geometry",
            {"confusion": 0.85, "request_representation": 0.7, "graphical": 0.6},
            secondary=["jemh102__quadratic_coefficients", "jemh104__roots_of_quadratic_equation"]),
    _anchor("i think the discriminant is zero so one root",
            "LEARNING", "jemh104__discriminant_nature_of_roots",
            {"answer_attempt": 0.9, "procedural_focus": 0.5}, answer=True,
            secondary=["jemh104__quadratic_formula", "jemh104__roots_of_quadratic_equation"]),
    _anchor("yes that makes sense now, got it",
            "LEARNING", INHERIT, {"acknowledgment": 0.95}),
    _anchor("can you explain that again in easier words",
            "LEARNING", INHERIT, {"simplification_request": 0.9, "confusion": 0.4}),
    _anchor("hi wini how are you today",
            "SOCIAL", INHERIT, {}),
    _anchor("are you a real person or a robot",
            "META_CAPABILITY", INHERIT, {}),
    _anchor("what is the capital of france",
            "OFF_DOMAIN_ACADEMIC", INHERIT, {}),
    _anchor("i'm tired, can we stop for today",
            "SESSION_CONTROL", INHERIT, {}),
    _anchor("this is boring i don't want to do maths",
            "SESSION_CONTROL", INHERIT, {}),
    _anchor("i'm really scared i will fail my exam",
            "EMOTIONAL", INHERIT, {"anxiety": 0.8}),
    _anchor("i feel like i want to hurt myself",
            "SAFETY", INHERIT, {}, safety=True),
    _anchor("asdkfj qwptz",
            "NONSENSE", INHERIT, {}),
    _anchor("ok but what is a factor, i forgot",
            "LEARNING", "jemh101__prime_factorization_hcf_lcm",
            {"question": 0.9, "prerequisite_awareness": 0.6},
            secondary=["jemh101__fundamental_theorem_of_arithmetic", "jemh102__zero_of_polynomial"]),
    _anchor("actually can we switch to trigonometry now",
            "LEARNING", "jemh108__intro_trigonometry", {"topic_shift": 0.85},
            secondary=["jemh108__fundamental_trig_ratios"]),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _sample_train_anchors(labels: List[str], n: int = 6, seed: int = 42) -> List[dict]:
    """A few TRAIN-split rows to illustrate signal+concept grounding (§5.1: anchors
    from TRAIN only, never val/test). Best-effort; returns [] if files are absent."""
    if not (SPLITS.exists() and CURATED.exists()):
        return []
    try:
        from cognitive_classifier.label_space import canonicalize_labels
        splits = json.loads(SPLITS.read_text(encoding="utf-8"))
        rows = json.loads(CURATED.read_text(encoding="utf-8"))
        train_ids = splits["row_ids"]["train"]
        label_set = set(labels)
        rng = random.Random(seed)
        picks, seen = [], set()
        for idx in rng.sample(train_ids, min(len(train_ids), 400)):
            row = rows[idx]
            cid = row.get("concept_id") or INHERIT
            utt = (row.get("student_utterance") or "").strip()
            if not utt or utt in seen:
                continue
            sigs = [s for s in canonicalize_labels(row.get("miniLM_labels", "")) if s in label_set]
            if not sigs:
                continue
            seen.add(utt)
            picks.append({"utterance": utt, "concept_id": cid,
                          "signals": sigs[:4]})
            if len(picks) >= n:
                break
        return picks
    except Exception:  # noqa: BLE001 — anchors are illustrative; never fail the build on them
        return []


def render_context(labels, concept_ids, concept_names, train_anchors) -> str:
    """The cached static block: the system-instruction body sent (or cached) once."""
    lines: List[str] = []
    lines.append("# Wini perception task\n")
    lines.append(
        "You are the PERCEPTION layer of a Class 10 maths tutor for a child. You do NOT teach "
        "and you do NOT decide what to do next. You only READ one student utterance and output a "
        "single structured JSON object describing it. Deterministic downstream code makes every "
        "decision and writes all state.\n")
    lines.append("Return ONLY the JSON object matching the provided schema. Default to ABSENT: "
                 "flag a signal only when the utterance clearly shows it (a quotable span), and "
                 "default `concept_id` to `INHERIT_CURRENT_CONCEPT` unless a concept is clearly named "
                 "or implied. `temperature` is 0 — be consistent and conservative, never generous.\n")

    lines.append("\n## Intents (choose exactly one `intent`)\n")
    for name in INTENTS:
        lines.append(f"- **{name}**: {INTENT_DEFS[name]}")
    lines.append("\nOnly `LEARNING` turns move learner state. `also_learning=true` marks a "
                 "non-LEARNING turn that ALSO contains a genuine maths ask. SAFETY: when in doubt, "
                 "choose SAFETY and set `safety=true`.\n")

    lines.append("\n## Signals (`signal_scores`: each 0.0-1.0; OMIT or 0.0 when absent)\n")
    lines.append("For a non-LEARNING intent, signals are almost always empty. Never flag `confusion` "
                 "for an acknowledgment or a neutral next-step request.\n")
    for lab in labels:
        lines.append(f"- `{lab}`: {SIGNAL_DEFS[lab]}")

    lines.append("\n## Concept catalog (`concept_id`: one of these ids, or "
                 "`INHERIT_CURRENT_CONCEPT` to abstain)\n")
    lines.append("Pick the single best-matching id. If the utterance names no concept confidently, "
                 "use `INHERIT_CURRENT_CONCEPT`.\n")
    lines.append("`secondary_concepts`: whenever `concept_id` IS a catalog id, ALWAYS also list the "
                 "2-3 next-most-plausible catalog ids (closely related concepts or plausible "
                 "alternate readings of the utterance) — never leave it empty in that case. Leave it "
                 "empty only when abstaining with `INHERIT_CURRENT_CONCEPT`.\n")
    lines.append("The per-turn context may include a `candidate_concepts` list — retrieval hints "
                 "ranked by embedding similarity. The correct concept is usually among them, so "
                 "consider them first for `concept_id` and `secondary_concepts`; but they are hints, "
                 "not a restriction — any catalog id is allowed, and you must still abstain to "
                 "`INHERIT_CURRENT_CONCEPT` when the utterance names no concept.\n")
    for cid, name in zip(concept_ids, concept_names):
        lines.append(f"- `{cid}` = {name}")

    lines.append("\n## Examples\n")
    for a in FEWSHOT_ANCHORS:
        lines.append(f"STUDENT: {a['utterance']}")
        lines.append("JSON: " + json.dumps(a["perception"], ensure_ascii=False))
    if train_anchors:
        lines.append("\n### Signal-grounding examples (from training data)\n")
        for a in train_anchors:
            lines.append(f"STUDENT: {a['utterance']}  ->  concept={a['concept_id']}, "
                         f"signals={a['signals']}")
    lines.append("")
    return "\n".join(lines)


def build(write: bool = True) -> dict:
    labels = json.loads(LABEL_SPACE.read_text(encoding="utf-8"))["labels"]
    meta = json.loads(CONCEPTS_META.read_text(encoding="utf-8"))
    concept_ids = meta["concept_ids"]
    concept_names = meta["concept_names"]

    # Drift guards (§5.4): definitions must cover EXACTLY the shipped labels.
    missing = set(labels) - set(SIGNAL_DEFS)
    extra = set(SIGNAL_DEFS) - set(labels)
    if missing or extra:
        raise SystemExit(
            f"SIGNAL_DEFS out of sync with label_space.json — missing={sorted(missing)} "
            f"extra={sorted(extra)}. Reconcile before building (CLAUDE.md: derive from artifacts).")
    # Anchor concept ids must be in-catalog (or the sentinel).
    catalog = set(concept_ids) | {INHERIT}
    for a in FEWSHOT_ANCHORS:
        cid = a["perception"]["concept_id"]
        if cid not in catalog:
            raise SystemExit(f"few-shot anchor references out-of-catalog concept_id {cid!r}")
        for s in a["perception"]["signal_scores"]:
            if s not in labels:
                raise SystemExit(f"few-shot anchor references out-of-space signal {s!r}")

    train_anchors = _sample_train_anchors(labels)
    context = render_context(labels, concept_ids, concept_names, train_anchors)

    enums = {
        "intents": INTENTS,
        "labels": labels,
        "concept_ids": concept_ids,
        "concept_names": concept_names,
        "inherit_sentinel": INHERIT,
    }
    manifest = {
        "sources": {
            "label_space.json": {"sha16": _sha(LABEL_SPACE), "n_labels": len(labels)},
            "concepts_meta.json": {"sha16": _sha(CONCEPTS_META), "n_concepts": len(concept_ids)},
        },
        "n_intents": len(INTENTS),
        "n_fewshot_anchors": len(FEWSHOT_ANCHORS),
        "n_train_anchors": len(train_anchors),
        "context_chars": len(context),
    }

    if write:
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        (BUILD_DIR / "perception_enums.json").write_text(
            json.dumps(enums, ensure_ascii=False, indent=2), encoding="utf-8")
        (BUILD_DIR / "perception_context.md").write_text(context, encoding="utf-8")
        (BUILD_DIR / "perception_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"enums": enums, "context": context, "manifest": manifest}


def main() -> None:
    out = build(write=True)
    m = out["manifest"]
    print(f"built perception artifacts -> {BUILD_DIR}")
    print(f"  intents={m['n_intents']}  labels={m['sources']['label_space.json']['n_labels']}"
          f"  concepts={m['sources']['concepts_meta.json']['n_concepts']}")
    print(f"  anchors: {m['n_fewshot_anchors']} authored + {m['n_train_anchors']} train")
    print(f"  cached context block: {m['context_chars']} chars")


if __name__ == "__main__":
    main()
