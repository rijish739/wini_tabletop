"""generate_t2_t3_samples.py
─────────────────────────────────────────────────────────────────────────────
T2 (acknowledgment) + T3 (weak-label data pass) sample generator for
`exemplar_dataset_10000_fixed.json`. Produces:

  - ~300 pure-ack utterances (each verified to pass cues.is_pure_ack)
  - 100 each for the long-tail labels:
        answer_attempt, self_correction, high_confidence,
        hint_dependency, representation_shift

Every emitted row:
  - keeps the dataset schema (utterance / concept_id / miniLM_labels /
    hope_signals / target_policy_action / category)
  - carries an extra `split: "train"` field (CLAUDE.md mandate: supplementary
    rows never enter val/test of the original 10k; frozen splits.json indexes
    rows 0..9999 only, so appended rows declare themselves as train).
  - uses ONLY the canonical 16 actions + the canonical 37 labels, except for
    the new `acknowledgment` label introduced by T2.

Style/policy choices follow PHASE1_QUERY_RESPONSES T2 + IMPLEMENTATION_TASKS T2/T3:
  - pure acks → action METACOGNITIVE_REFLECT (default per T2) with a small set
    routed to RESUME_STATE when the ack also signals "ready for next".
  - `acknowledgment` is the primary label; `confusion`/`low_confidence` are NEVER
    on a pure-ack row (T2.Q2 curation rule).
  - Surface tokens VARY (different concepts, fillers, hi-eng/Indianisms) so the
    bank can't overfit a literal (T2.Q4).

Usage:
  python dataset/generate_t2_t3_samples.py            # dry-run: prints counts + samples
  python dataset/generate_t2_t3_samples.py --apply    # backup + append + report
"""
from __future__ import annotations
import json
import sys
import shutil
import random
from collections import Counter
from pathlib import Path

# Make project root importable for cues
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cognitive_classifier.cues import is_pure_ack  # noqa: E402

SRC = ROOT / "dataset" / "exemplar_dataset_10000_fixed.json"
BACKUP = ROOT / "dataset" / "exemplar_dataset_10000_fixed.backup_pret2t3.json"
REPORT = ROOT / "dataset" / "t2_t3_added_rows_report.md"

VALID_ACTIONS = {
    "EXPLAIN", "REPRESENTATION_TRANSLATION", "ENCOURAGE", "SOCRATIC_Q", "REVIEW",
    "BRIDGE_RECAP", "RESUME_STATE", "WORKED_EXAMPLE", "METACOGNITIVE_REFLECT",
    "QUIZ", "TRANSFER_PROBLEM", "VERBAL_ANALOGY", "REQUEST_HINT",
    "ANALOGOUS_EXAMPLE", "MISCONCEPTION_PROBE", "ISOMORPHIC_PRACTICE",
}

# Canonical 37 labels + the new T2 label
CANONICAL_LABELS = {
    "abstraction_attempt", "algebraic", "answer_attempt", "anxiety",
    "cognitive_overload", "conflict", "confusion", "curiosity", "diagrammatic",
    "disengagement", "environmental_feedback", "example_request", "frustration",
    "graphical", "high_confidence", "hint_dependency", "low_confidence",
    "misconception_clue", "physical", "prerequisite_awareness",
    "prerequisite_weakness", "procedural_focus", "question", "ready_for_next",
    "recurring_error", "representation_shift", "request_hint",
    "request_representation", "self_correction", "self_monitoring",
    "shortcut_seeking", "simplification_request", "skepticism", "tabular",
    "topic_shift", "transfer_attempt", "verbal_analogy",
}
NEW_LABEL = "acknowledgment"
VALID_LABELS = CANONICAL_LABELS | {NEW_LABEL}

# Concept ids drawn from the live distribution (top NCERT chapters of cls 10).
CONCEPT_POOL = [
    "INHERIT_CURRENT_CONCEPT",
    "jemh101__proof_by_contradiction_method",
    "jemh101__proving_irrationality_root_n",
    "jemh101__hcf_lcm_product_relation",
    "jemh101__prime_factorization_hcf_lcm",
    "jemh102__quadratic_zero_geometry",
    "jemh103__system_classification",
    "jemh103__graphical_method_solving",
    "jemh103__elimination_method",
    "jemh104__quadratic_formula",
    "jemh104__discriminant_nature_of_roots",
    "jemh104__solving_by_factorization",
    "jemh105__nth_term_formula",
    "jemh105__sum_n_terms_formula",
    "jemh105__ap_applications",
    "jemh106__basic_proportionality_theorem",
    "jemh106__similar_figures",
    "jemh106__triangle_similarity_criteria_intro",
    "jemh107__collinearity_of_points",
    "jemh107__section_formula",
    "jemh108__fundamental_trig_ratios",
    "jemh108__trig_ratios_specific_angles",
    "jemh108__pythagorean_trig_identities",
    "jemh108__proving_trig_identities",
    "jemh108__intro_trigonometry",
    "jemh110__tangent_radius_perpendicularity",
    "jemh110__equal_tangent_lengths",
    "jemh112__surface_area_combined_solids",
    "jemh113__mean_grouped_data",
    "jemh114__theoretical_probability_formula",
]


def label_str(*labels) -> str:
    seen = []
    for l in labels:
        if l and l not in seen:
            seen.append(l)
    for l in seen:
        assert l in VALID_LABELS, f"invalid label: {l}"
    return ", ".join(sorted(seen))


# ── 1) Pure-ack utterance pool ──────────────────────────────────────────────
# All strings must pass `is_pure_ack`: contain an ACK_RE token AND not contain
# "?", a WH-word, or any of {but, because, since, as}. We assert this at the end.

# Plain affirmations
_PLAIN = [
    "okay", "ok", "yes", "yeah", "yep", "ya", "okayy", "okayyy", "okie",
    "okies", "right right", "yes yes", "yeah yeah", "yup", "okk",
]

# "got it" family
_GOTIT = [
    "got it", "ok got it", "okay got it", "yes got it", "yeah got it",
    "ya got it", "yep got it", "alright got it", "got it sir", "got it ma'am",
    "got it now", "got it finally", "got it fully", "i got it",
    "i got it now", "okay i got it", "ya i got it", "yes i got it",
]

# "makes sense" family
_MAKESSENSE = [
    "makes sense", "ok makes sense", "okay makes sense", "yes makes sense",
    "this makes sense", "now it makes sense", "it makes sense now",
    "yeah makes sense", "ya makes sense", "alright makes sense",
    "totally makes sense", "fully makes sense", "perfectly makes sense",
]

# "understood" family
_UNDERSTOOD = [
    "understood", "i understood", "yes understood", "okay understood",
    "ok understood", "ya understood", "yeah understood", "i have understood",
    "i had understood", "understood sir", "understood ma'am",
    "understood now", "i understood now",
]

# "i get it" family
_IGETIT = [
    "i get it", "okay i get it", "ok i get it", "yes i get it",
    "yeah i get it", "ya i get it", "alright i get it", "i get it now",
    "i get it fully", "i get it sir", "i get it ma'am",
]

# "clear" family
_CLEAR = [
    "clear now", "all clear", "everything clear", "this is clear now",
    "okay clear now", "yes all clear", "yeah clear now", "ya clear",
    "totally clear", "perfectly clear", "fully clear", "ok clear",
]

# "that helps" family
_THATHELPS = [
    "that helps", "that really helps", "it helped", "yes that helps",
    "yeah that helps", "okay that helps", "ya that helps", "this helped",
    "this explained it", "it explained it well", "that explained it",
]

# "thanks" family
_THANKS = [
    "thanks", "thank you", "thank you sir", "thank you ma'am",
    "thanks a lot", "thanks so much", "thanks sir", "thanks ma'am",
    "ya thanks", "ok thanks", "okay thanks", "yes thanks",
    "thank you so much", "thanks for explaining", "thanks i got it",
]

# Topic-suffixed acks (vary surface tokens per T2.Q4) — concept name only,
# never a WH-word or `?`
_TOPIC_SUFFIXES_GOTIT = [
    "got it about quadratic formula", "okay got it about BPT",
    "got it about similar triangles", "yes got it about nth term",
    "got it about discriminant", "got it about probability",
    "okay got it about distance formula", "got it about HCF LCM",
    "yes got it about trig ratios", "got it about section formula",
    "got it about combined solids", "got it about mean of grouped data",
    "got it about elimination method", "got it about graphical method",
    "got it about contradiction proof", "okay got it about tangent length",
    "got it about prime factorization", "yes got it about identities",
    "got it about parabola shape", "got it about AP sum formula",
]
_TOPIC_SUFFIXES_CLEAR = [
    "quadratic formula clear now", "BPT clear now", "tangent property clear now",
    "trig identities clear now", "nth term formula clear now",
    "discriminant clear now", "AP sum clear now", "similar triangles clear now",
    "section formula clear now", "HCF LCM relation clear now",
    "contradiction method clear now", "probability formula clear now",
    "mean grouped data clear now", "elimination method clear now",
    "graphical method clear now", "collinearity clear now",
    "tangent radius rule clear now", "surface area combined solids clear now",
]
_TOPIC_SUFFIXES_MAKESSENSE = [
    "the proof makes sense now", "the formula makes sense now",
    "this method makes sense now", "the theorem makes sense now",
    "the relation makes sense now", "the rule makes sense now",
    "the derivation makes sense now", "the steps make sense now",
    "the identity makes sense now", "the diagram makes sense now",
    "this concept makes sense now", "this part makes sense now",
]

# Ready-for-next acks (still pure-ack: no `?`, no WH-word, no but/because/since/as)
_READY_NEXT = [
    "ok i got it lets move on", "got it ready for next",
    "yes got it ready for next", "okay i got it lets continue",
    "alright got it lets continue", "got it lets go to next part",
    "yeah got it ready to continue", "ok got it lets do next one",
    "okay understood ready for next", "got it ready for next concept",
    "ok this is clear ready to continue", "yes understood ready to continue",
    "got it ready to move on", "okay makes sense ready to continue",
    "yeah got it ready to continue", "ya got it ready for next",
    "ok all clear ready to continue", "got it now ready for next",
    "okay got it lets move on now", "yes got it lets continue",
]

# High-confidence emphatic acks (still pure-ack)
_EMPHATIC = [
    "yes i totally got it", "okay i fully got it", "ya i completely got it",
    "yeah i finally got it", "ok i really got it", "i totally understood",
    "i fully understood", "i completely understood", "ya i finally understood",
    "i got it perfectly", "i got it really well", "ya it is super clear now",
    "ok this is totally clear", "yes this is fully clear",
    "yeah this is perfectly clear", "ok i got the whole idea",
]

# Hindi-mixed acks (no disqualifiers; using English ACK_RE token + Hindi filler)
# IMPORTANT: avoid "haan kyunki" (because) etc.
_HINDI_MIXED = [
    "ok ji got it", "haan got it", "haan okay got it", "haan yes got it",
    "ji got it", "ok ji understood", "haan understood",
    "ji understood now", "ji this is clear now", "haan clear now",
    "ji yes clear now", "thik hai got it", "thik hai understood",
    "haan ji got it", "haan ji makes sense", "ji okay i got it",
    "ji yes i got it", "ji thank you", "haan thank you",
    "haan ji ok", "ji ok all clear",
]


def build_ack_pool():
    pool = []
    pool += _PLAIN
    pool += _GOTIT
    pool += _MAKESSENSE
    pool += _UNDERSTOOD
    pool += _IGETIT
    pool += _CLEAR
    pool += _THATHELPS
    pool += _THANKS
    pool += _TOPIC_SUFFIXES_GOTIT
    pool += _TOPIC_SUFFIXES_CLEAR
    pool += _TOPIC_SUFFIXES_MAKESSENSE
    pool += _READY_NEXT
    pool += _EMPHATIC
    pool += _HINDI_MIXED
    return pool


def gen_acknowledgment_rows():
    rng = random.Random(0xACE)
    pool = build_ack_pool()
    # dedupe, normalize whitespace
    pool = sorted({" ".join(s.split()) for s in pool})

    # If pool < 300, extend by appending a contextual sentence (still pure-ack)
    # safe trailers — none contain ?/WH/but/because/since/as
    safe_trailers = [
        "", " sir", " ma'am", " mam", " thanks", " ji", " yaar",
        " thank you", " really", " finally", " now",
    ]
    extended = set(pool)
    for s in pool:
        for tr in safe_trailers:
            cand = (s + tr).strip()
            if is_pure_ack(cand):
                extended.add(cand)
            if len(extended) >= 360:
                break
        if len(extended) >= 360:
            break

    candidates = sorted(extended)
    rng.shuffle(candidates)

    rows = []
    target = 300
    for utt in candidates:
        if len(rows) >= target:
            break
        if not is_pure_ack(utt):
            continue
        # Pick policy + labels by surface shape
        labels = [NEW_LABEL]
        action = "METACOGNITIVE_REFLECT"
        hope = "Active engagement, High ct_score, Moderate ki_score, High confidence"

        low = utt.lower()
        ready_markers = ("next", "continue", "move on", "lets go", "lets do")
        emph_markers = ("totally", "fully", "completely", "finally", "perfectly",
                        "really", "whole idea", "super clear")
        if any(m in low for m in ready_markers):
            labels += ["ready_for_next", "high_confidence", "self_monitoring"]
            action = "RESUME_STATE"
            hope = "High confidence, Mastery threshold met, Active engagement, High ct_score"
        elif any(m in low for m in emph_markers):
            labels += ["high_confidence", "self_monitoring"]
            hope = "High confidence, Mastery threshold met, Active engagement, High ct_score"
        elif "thank" in low:
            labels += ["self_monitoring"]
            hope = "Active engagement, High ct_score, High confidence"

        rows.append({
            "student_utterance": utt,
            "concept_id": "INHERIT_CURRENT_CONCEPT",
            "miniLM_labels": label_str(*labels),
            "hope_signals": hope,
            "target_policy_action": action,
            "category": 4,
            "split": "train",
        })
    return rows


# ── 2) answer_attempt rows (100) ────────────────────────────────────────────
_AA_STEMS = [
    "i think the answer is", "i think it is", "i think it's", "is the answer",
    "is it", "my answer is", "i got", "i wrote", "i guessed it as",
    "i'm guessing it is", "i am guessing it's", "answer is", "answer should be",
]
_AA_VALUES = [
    "5", "12", "0", "1", "-3", "7", "3/4", "1/2", "-1/2", "sqrt(2)",
    "2 + sqrt(3)", "x = 2", "x = -1", "x = 3 or 5", "y = 0", "9/16",
    "8 cm", "10 m", "100", "25/4", "k = 4", "n = 10", "r = 3", "p = 7",
    "real and equal", "real and distinct", "no real roots", "12 cm^2",
    "side = 8", "AB = 6", "ratio 2:3", "5 sin theta", "1 + cos theta",
]
_AA_CONCEPT_PHRASES = [
    "for this quadratic", "for D = b^2-4ac", "for the discriminant",
    "for nth term of AP", "for sum of n terms", "for area of segment",
    "for similar triangles ratio", "for BPT", "for HCF and LCM product",
    "for prime factorization", "for the section formula", "for distance formula",
    "for sin 60 cos 30", "for tan 45", "for probability of getting tail",
    "for combined solid surface area", "for mean of grouped data",
    "for the elimination method", "for graphical solution",
]


def gen_answer_attempt_rows():
    rng = random.Random(0xA1)
    rows = []
    seen = set()
    for _ in range(800):
        if len(rows) >= 100:
            break
        stem = rng.choice(_AA_STEMS)
        val = rng.choice(_AA_VALUES)
        ctx = rng.choice(_AA_CONCEPT_PHRASES)
        if rng.random() < 0.55:
            utt = f"{stem} {val} {ctx}, is that right?"
            labels = ["answer_attempt", "algebraic", "curiosity", "procedural_focus", "question"]
            if rng.random() < 0.5:
                labels.append("low_confidence")
            action = "SOCRATIC_Q"
            hope = "Active engagement, High ct_score, Moderate ki_score, Low confidence"
        elif rng.random() < 0.5:
            utt = f"{stem} {val} {ctx}, i think i did it correctly"
            labels = ["answer_attempt", "algebraic", "high_confidence", "procedural_focus", "self_monitoring"]
            action = "SOCRATIC_Q"
            hope = "Active engagement, High ct_score, High ki_score, High confidence"
        else:
            utt = f"{stem} {val} {ctx}"
            labels = ["answer_attempt", "algebraic", "procedural_focus", "self_monitoring"]
            if rng.random() < 0.5:
                labels.append("low_confidence")
                hope = "Active engagement, High ct_score, Moderate ki_score, Low confidence"
            else:
                hope = "Active engagement, High ct_score, High ki_score, Moderate confidence"
            action = "METACOGNITIVE_REFLECT"
        if utt in seen:
            continue
        seen.add(utt)
        rows.append({
            "student_utterance": utt,
            "concept_id": rng.choice(CONCEPT_POOL[1:]),  # avoid INHERIT for these
            "miniLM_labels": label_str(*labels),
            "hope_signals": hope,
            "target_policy_action": action,
            "category": rng.choice([6, 7, 8]),
            "split": "train",
        })
    return rows[:100]


# ── 3) self_correction rows (100) ───────────────────────────────────────────
_SC_STEMS = [
    "wait", "actually", "oh no", "hold on", "no wait", "wait wait",
    "sorry sir", "sorry ma'am", "i mean", "my bad",
]
_SC_REVISIONS = [
    "i was wrong about this", "i think i did this wrong", "i confused myself",
    "i did this step wrong", "i applied the wrong formula", "i mixed up the signs",
    "i swapped the values", "i used the wrong identity", "i wrote it the wrong way",
    "i did the calculation wrong", "i used (n-1) instead of n", "i forgot the minus",
    "i missed the squared part", "i wrote the ratio reverse", "i used sin not cos",
    "i used the wrong formula here", "let me redo this part", "let me try again",
    "i need to redo this step", "let me reconsider this answer",
]
_SC_CONCEPTS = [
    "for this quadratic", "in the nth term step", "for similar triangles",
    "for the discriminant case", "for BPT ratio", "for sum of n terms",
    "for HCF LCM relation", "for the trig identity", "in the elimination step",
    "in the substitution step", "for distance formula", "for section formula",
    "for area of segment", "for combined solid", "for mean grouped data",
    "in the probability count", "in the prime factorization",
]


def gen_self_correction_rows():
    rng = random.Random(0x5C)
    rows = []
    seen = set()
    for _ in range(2000):
        if len(rows) >= 100:
            break
        stem = rng.choice(_SC_STEMS)
        rev = rng.choice(_SC_REVISIONS)
        ctx = rng.choice(_SC_CONCEPTS)
        if rng.random() < 0.45:
            utt = f"{stem}, {rev} {ctx}"
        elif rng.random() < 0.5:
            utt = f"{stem}, i think {rev} {ctx}"
        else:
            utt = f"{stem}, {rev}, can you check {ctx}?"
        labels = ["self_correction", "self_monitoring"]
        if "answer" in rev or "redo" in rev or "reconsider" in rev:
            labels.append("answer_attempt")
        if "wrong" in rev or "confused" in rev or "mixed" in rev:
            labels.append("low_confidence")
            labels.append("confusion")
        if "formula" in rev or "identity" in rev or "ratio" in rev or "signs" in rev:
            labels.append("algebraic")
            labels.append("procedural_focus")
        if "?" in utt:
            labels.append("question")
            action = "REVIEW"
            hope = "Moderate load_risk, Active misconception check, Active engagement, High ct_score"
        else:
            action = "BRIDGE_RECAP" if rng.random() < 0.5 else "EXPLAIN"
            hope = "Moderate load_risk, Active engagement, High ct_score, Moderate ki_score"
        if utt in seen:
            continue
        seen.add(utt)
        rows.append({
            "student_utterance": utt,
            "concept_id": rng.choice(CONCEPT_POOL[1:]),
            "miniLM_labels": label_str(*labels),
            "hope_signals": hope,
            "target_policy_action": action,
            "category": rng.choice([4, 7, 8]),
            "split": "train",
        })
    return rows[:100]


# ── 4) high_confidence rows (100) ───────────────────────────────────────────
# T3 calls out polarity blindness ("so easy" ≈ "so hard"); ensure the strongest
# emphatic confidence markers are present so the surface cues fire ("easy",
# "sure", "obviously"), per the cues.py CONFIDENT_RE intent.
_HC_STEMS = [
    "this is so easy", "this is super easy", "this part is easy",
    "i know this for sure", "i am sure about this", "this is obvious",
    "obviously the answer is straightforward", "i can do this easily",
    "i already know this from tuition", "i already know this from class 9",
    "this is simple for me", "this part is simple for me",
    "i know this concept very well", "this is no problem for me",
    "i find this very easy", "this is a piece of cake for me",
]
_HC_TOPICS = [
    "the quadratic formula", "BPT theorem", "discriminant for nature of roots",
    "nth term of AP", "sum of n terms", "similar figures",
    "HCF LCM product relation", "prime factorization", "the distance formula",
    "section formula", "tangent radius rule", "trig ratios for 30 45 60",
    "Pythagorean identity", "mean of grouped data by direct method",
    "elimination method", "graphical method", "probability for a fair coin",
    "surface area of cylinder", "the contradiction proof method",
]
_HC_TAILS = [
    "lets move on please", "can we move to the next part",
    "lets do something harder now", "lets do tougher problems",
    "can we go to the next concept", "ready for next",
    "lets continue with the next topic", "lets skip this and try harder ones",
    "give me a harder one", "give me a tricky one",
]


def gen_high_confidence_rows():
    rng = random.Random(0xC0FFEE)
    rows = []
    seen = set()
    for _ in range(3000):
        if len(rows) >= 100:
            break
        stem = rng.choice(_HC_STEMS)
        topic = rng.choice(_HC_TOPICS)
        tail = rng.choice(_HC_TAILS)
        if rng.random() < 0.6:
            utt = f"{stem}, {topic} is clear, {tail}"
        else:
            utt = f"{stem}, i know {topic} properly, {tail}"
        labels = ["high_confidence", "ready_for_next", "self_monitoring"]
        if "next" in tail or "continue" in tail:
            labels.append("topic_shift")
            action = "RESUME_STATE"
        elif "harder" in tail or "tougher" in tail or "tricky" in tail:
            labels.append("transfer_attempt")
            action = "TRANSFER_PROBLEM"
        else:
            action = "QUIZ"
        labels.append("procedural_focus")
        hope = "High confidence, Mastery threshold met, Active engagement, High ct_score"
        if utt in seen:
            continue
        seen.add(utt)
        rows.append({
            "student_utterance": utt,
            "concept_id": rng.choice(CONCEPT_POOL[1:]),
            "miniLM_labels": label_str(*labels),
            "hope_signals": hope,
            "target_policy_action": action,
            "category": 4,
            "split": "train",
        })
    return rows[:100]


# ── 5) hint_dependency rows (100) ───────────────────────────────────────────
_HD_OPENS = [
    "i can't even start", "i can't start this", "i cannot begin this",
    "i don't know what to do next", "i don't know the first step",
    "my mind is blanking out", "my mind is going blank", "i am totally stuck",
    "i'm stuck again", "stuck like always", "i am stuck on the very first step",
    "i can't think of where to start", "i cannot move ahead",
]
_HD_REQS = [
    "just give me a hint", "please give me a nudge", "give me a clue",
    "tell me what to do first", "tell me how to start", "tell me the first step",
    "just give me the first step", "can you nudge me", "just a small hint please",
    "give me one hint please", "nudge me to start", "give me a tiny hint",
    "just hint me", "tell me where to start", "tell me how to begin",
]
_HD_TOPICS = [
    "for this quadratic problem", "for BPT proof", "for this nth term sum",
    "for this discriminant question", "for this similar triangles problem",
    "for this HCF LCM problem", "for this distance formula sum",
    "for this section formula problem", "for this trig identity proof",
    "for this AP sum problem", "for this irrational proof", "for this probability problem",
    "for this graphical method question", "for this elimination problem",
    "for this combined solid surface area sum",
    "for this mean of grouped data problem",
]


def gen_hint_dependency_rows():
    rng = random.Random(0xD1B)
    rows = []
    seen = set()
    for _ in range(3000):
        if len(rows) >= 100:
            break
        op = rng.choice(_HD_OPENS)
        rq = rng.choice(_HD_REQS)
        tp = rng.choice(_HD_TOPICS)
        if rng.random() < 0.5:
            utt = f"{op} {tp}, {rq}?"
        else:
            utt = f"{op}, {rq} {tp}?"
        labels = ["hint_dependency", "request_hint", "question", "curiosity", "self_monitoring"]
        # Common co-occurring labels in the existing 64 hint_dependency rows
        if rng.random() < 0.4:
            labels.append("cognitive_overload")
        if rng.random() < 0.4:
            labels.append("low_confidence")
            labels.append("confusion")
        if rng.random() < 0.35:
            labels.append("algebraic")
        if rng.random() < 0.3:
            labels.append("procedural_focus")
        action = "REQUEST_HINT"
        hope = "Active hint_dependency, Active engagement, High ct_score, Moderate ki_score"
        if utt in seen:
            continue
        seen.add(utt)
        rows.append({
            "student_utterance": utt,
            "concept_id": rng.choice(CONCEPT_POOL[1:]),
            "miniLM_labels": label_str(*labels),
            "hope_signals": hope,
            "target_policy_action": action,
            "category": rng.choice([5, 8]),
            "split": "train",
        })
    return rows[:100]


# ── 6) representation_shift rows (100) ──────────────────────────────────────
_RS_OPENS = [
    "this is hard to follow only in words", "all these symbols are confusing",
    "i can't picture this from text", "reading this is not helping me",
    "this is too abstract for me", "i learn better visually",
    "i need to see this", "this words-only explanation isn't clicking",
    "the formulas alone don't help", "words alone aren't working for me",
]
_RS_ASKS = [
    "can you draw it on a graph", "can you show it as a diagram",
    "can you visualize this for me", "can you show this graphically",
    "can you show me a chart for this", "can you draw the diagram for this",
    "can you put this on a number line", "can you show me a sketch",
    "can you show this on the axes", "can you make a visual for this",
    "can you draw it for me", "can you graph this please",
    "can you show me on a figure", "can you turn this into a picture",
    "can you display it visually",
]
_RS_TOPICS = [
    "for the quadratic", "for BPT", "for similar triangles",
    "for the nth term of AP", "for the discriminant cases",
    "for HCF LCM relation", "for the distance formula",
    "for the section formula", "for the trig ratios",
    "for the tangent property", "for the contradiction proof",
    "for surface area of combined solid", "for mean of grouped data",
    "for graphical method", "for probability of dice outcomes",
]


def gen_representation_shift_rows():
    rng = random.Random(0xBEEF)
    rows = []
    seen = set()
    for _ in range(3000):
        if len(rows) >= 100:
            break
        op = rng.choice(_RS_OPENS)
        ask = rng.choice(_RS_ASKS)
        tp = rng.choice(_RS_TOPICS)
        utt = f"{op}, {ask} {tp}?"
        labels = ["representation_shift", "request_representation", "curiosity",
                  "question", "environmental_feedback"]
        # surface modality cue
        if "graph" in ask or "axes" in ask or "number line" in ask:
            labels.append("graphical")
        elif "diagram" in ask or "figure" in ask or "sketch" in ask \
                or "picture" in ask or "draw" in ask or "chart" in ask \
                or "visual" in ask:
            labels.append("diagrammatic")
        # abstraction signal on the open
        if "abstract" in op or "symbols" in op or "formulas alone" in op:
            labels.append("abstraction_attempt")
        if rng.random() < 0.35:
            labels.append("cognitive_overload")
        if rng.random() < 0.3:
            labels.append("simplification_request")
        action = "REPRESENTATION_TRANSLATION"
        hope = "Moderate load_risk, Active engagement, High ct_score, Moderate ki_score"
        if utt in seen:
            continue
        seen.add(utt)
        rows.append({
            "student_utterance": utt,
            "concept_id": rng.choice(CONCEPT_POOL[1:]),
            "miniLM_labels": label_str(*labels),
            "hope_signals": hope,
            "target_policy_action": action,
            "category": 1,
            "split": "train",
        })
    return rows[:100]


def main():
    apply = "--apply" in sys.argv

    ack_rows = gen_acknowledgment_rows()
    aa_rows = gen_answer_attempt_rows()
    sc_rows = gen_self_correction_rows()
    hc_rows = gen_high_confidence_rows()
    hd_rows = gen_hint_dependency_rows()
    rs_rows = gen_representation_shift_rows()

    all_new = ack_rows + aa_rows + sc_rows + hc_rows + hd_rows + rs_rows

    # ── Validation ──
    fails = []
    for r in ack_rows:
        if not is_pure_ack(r["student_utterance"]):
            fails.append(("ack not pure", r["student_utterance"]))
    # vocab + schema
    for r in all_new:
        for k in ("student_utterance", "concept_id", "miniLM_labels",
                  "hope_signals", "target_policy_action", "category", "split"):
            if k not in r:
                fails.append(("missing key " + k, r))
        if r["target_policy_action"] not in VALID_ACTIONS:
            fails.append(("invalid action", r))
        for l in r["miniLM_labels"].split(", "):
            if l and l not in VALID_LABELS:
                fails.append(("invalid label " + l, r))

    # primary-label sanity per weak label
    def has(r, lab): return lab in r["miniLM_labels"].split(", ")
    if not all(has(r, "acknowledgment") for r in ack_rows): fails.append(("ack missing label",))
    if not all(has(r, "answer_attempt") for r in aa_rows): fails.append(("aa missing label",))
    if not all(has(r, "self_correction") for r in sc_rows): fails.append(("sc missing label",))
    if not all(has(r, "high_confidence") for r in hc_rows): fails.append(("hc missing label",))
    if not all(has(r, "hint_dependency") for r in hd_rows): fails.append(("hd missing label",))
    if not all(has(r, "representation_shift") for r in rs_rows): fails.append(("rs missing label",))

    # No confusion / low_confidence on pure-ack rows (T2.Q2 rule)
    for r in ack_rows:
        labs = r["miniLM_labels"].split(", ")
        if "confusion" in labs or "low_confidence" in labs:
            fails.append(("ack has forbidden affect label", r))

    # uniqueness within new rows
    if len({r["student_utterance"] for r in all_new}) != len(all_new):
        fails.append(("duplicate utterances in new rows",))

    # uniqueness vs existing dataset
    existing = json.loads(SRC.read_text(encoding="utf-8"))
    existing_utts = {r["student_utterance"] for r in existing}
    dup_with_existing = sum(1 for r in all_new if r["student_utterance"] in existing_utts)
    if dup_with_existing:
        fails.append((f"{dup_with_existing} new utterances already in dataset",))

    print("=" * 70)
    print(f"  {'APPLY' if apply else 'DRY-RUN'}: T2 (acknowledgment) + T3 (weak labels)")
    print("=" * 70)
    print(f"acknowledgment:        {len(ack_rows)}")
    print(f"answer_attempt:        {len(aa_rows)}")
    print(f"self_correction:       {len(sc_rows)}")
    print(f"high_confidence:       {len(hc_rows)}")
    print(f"hint_dependency:       {len(hd_rows)}")
    print(f"representation_shift:  {len(rs_rows)}")
    print(f"TOTAL NEW ROWS:        {len(all_new)}")
    print(f"VALIDATION FAILURES:   {len(fails)}")
    if fails:
        for f in fails[:10]:
            print("  -", f)
        sys.exit(1)

    # action / category distributions
    act = Counter(r["target_policy_action"] for r in all_new)
    cat = Counter(r["category"] for r in all_new)
    print("\nAction distribution:")
    for a, c in act.most_common():
        print(f"  {a:24s} {c}")
    print("Category distribution:")
    for c, n in sorted(cat.items()):
        print(f"  cat {c}: {n}")

    if apply:
        shutil.copy2(SRC, BACKUP)
        new_data = existing + all_new
        SRC.write_text(json.dumps(new_data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        # report
        lines = [
            "# T2 + T3 supplementary rows",
            "",
            f"- Source/output: `exemplar_dataset_10000_fixed.json` (backup: `{BACKUP.name}`)",
            f"- Existing rows: {len(existing)}",
            f"- Added rows:    {len(all_new)}",
            f"- New total:     {len(new_data)}",
            "",
            "Added rows carry `split: \"train\"` (per CLAUDE.md: supplementary rows",
            "never enter val/test of the frozen 10k splits).",
            "",
            "## Per-label counts",
            "",
            f"- acknowledgment (T2):       {len(ack_rows)}",
            f"- answer_attempt:            {len(aa_rows)}",
            f"- self_correction:           {len(sc_rows)}",
            f"- high_confidence:           {len(hc_rows)}",
            f"- hint_dependency:           {len(hd_rows)}",
            f"- representation_shift:      {len(rs_rows)}",
            "",
            "## Action distribution on added rows", "",
        ]
        for a, c in act.most_common():
            lines.append(f"- {a}: {c}")
        REPORT.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nWrote: {SRC.name} (now {len(new_data)} rows), "
              f"{BACKUP.name}, {REPORT.name}")
    else:
        # sample preview
        print("\n-- 6 ack samples --")
        for r in ack_rows[:6]:
            print(f"  cat{r['category']} {r['target_policy_action']:22s}| "
                  f"[{r['miniLM_labels']}] | {r['student_utterance']}")
        for name, lst in [("answer_attempt", aa_rows), ("self_correction", sc_rows),
                          ("high_confidence", hc_rows), ("hint_dependency", hd_rows),
                          ("representation_shift", rs_rows)]:
            print(f"\n-- 3 {name} samples --")
            for r in lst[:3]:
                print(f"  cat{r['category']} {r['target_policy_action']:22s}| "
                      f"[{r['miniLM_labels'][:70]}] | {r['student_utterance'][:100]}")


if __name__ == "__main__":
    main()
