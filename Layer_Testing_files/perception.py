"""Layer 2 (Perception & Intent) Standalone Interactive Tester.

Run directly via:
    python Layer_Testing_files/perception.py
"""

from __future__ import annotations

import copy
import io
import re
import sys
from pathlib import Path
from typing import Any, Mapping

# Ensure UTF-8 stdout encoding for Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Ensure repository root and cloud_run_service are on sys.path
_PKG_DIR = Path(__file__).resolve().parent.parent
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

_CLOUD_RUN_DIR = _PKG_DIR / "cloud_run_service"
if str(_CLOUD_RUN_DIR) not in sys.path:
    sys.path.insert(0, str(_CLOUD_RUN_DIR))

from runtime.contracts import (
    DeviceCapabilities,
    TurnBudgets,
    TurnInput,
    deep_thaw,
)
from perception.route import RouteResult
from perception.interface import (
    Perception,
    PerceptionObservation,
    PerceptionRequest,
)


class PerceptionEngine:
    """Accurate perception engine for standalone testing.

    Performs stage A deterministic safety & nonsense gating, multi-class intent
    classification, NCERT concept resolution, and cognitive signal extraction.
    """

    _CONCEPT_MAP = [
        (r"\b(quadratic|quadratics|ax\^2|x\^2|roots of quadratic)\b", "jemh104__quadratic_equation_definition", "Quadratic Equations"),
        (r"\b(area of (a )?circle|sector|segment|arc length|radius|circumference)\b", "jemh111__area_of_sector", "Area Related to Circles"),
        (r"\b(trigonometry|trig|sin|cos|tan|cosec|sec|cot)\b", "jemh108__intro_trigonometry", "Introduction to Trigonometry"),
        (r"\b(heights and distances|angle of elevation|angle of depression|line of sight)\b", "jemh109__line_of_sight", "Applications of Trigonometry"),
        (r"\b(polynomial|polynomials|degree of polynomial|zeroes of polynomial)\b", "jemh102__polynomial_degree", "Polynomials"),
        (r"\b(real number|real numbers|prime factorization|hcf|lcm|irrational)\b", "jemh101__fundamental_theorem_of_arithmetic", "Real Numbers"),
        (r"\b(linear equation|pair of linear|substitution|elimination)\b", "jemh103__pair_linear_equations_intro", "Linear Equations"),
        (r"\b(arithmetic progression|ap|nth term|sum of ap|common difference)\b", "jemh105__ap_definition_identification", "Arithmetic Progressions"),
        (r"\b(triangle|triangles|similar figures|bpt|basic proportionality|pythagoras)\b", "jemh106__similar_figures", "Triangles"),
        (r"\b(coordinate|cartesian|distance formula|section formula|midpoint)\b", "jemh107__cartesian_coordinate_system", "Coordinate Geometry"),
        (r"\b(circle|circles|tangent|radius perpendicular|secant)\b", "jemh110__lines_and_circles_definitions", "Circles"),
        (r"\b(surface area|volume|cylinder|cone|sphere|hemisphere|frustum|composite solid)\b", "jemh112__surface_area_combined_solids", "Surface Areas and Volumes"),
        (r"\b(statistics|mean|median|mode|grouped data|frequency)\b", "jemh113__grouped_frequency_distribution", "Statistics"),
        (r"\b(probability|sample space|event|equally likely|favorable outcomes)\b", "jemh114__theoretical_probability_formula", "Probability"),
    ]

    _SAFETY_KEYWORDS = [
        "bomb", "kill", "suicide", "harm", "weapon", "abuse", "poison",
        "explode", "terrorist", "die", "hurt myself", "cut myself", "shoot"
    ]

    _GIBBERISH = ["asdf", "qwerty", "zxcv", "12345", ";;;", "hjkl", "tgbjk"]

    def perceive_input(self, text: str, session: Mapping[str, Any]) -> tuple[RouteResult, Mapping[str, Any]]:
        raw_text = text or ""
        norm_text = raw_text.lower().strip()
        clean_text = re.sub(r"[^\w\s]", " ", norm_text).strip()

        # -------------------------------------------------------------------
        # 1. Deterministic Stage A Gates: SAFETY & NONSENSE
        # -------------------------------------------------------------------
        if any(kw in norm_text or kw in clean_text for kw in self._SAFETY_KEYWORDS):
            route = RouteResult(
                primary="SAFETY",
                safety_alert=True,
                safety_tier=3,
                safety_category="urgent_danger",
                source="gate",
                reason="deterministic SAFETY lexicon match",
            )
            analysis = {
                "raw_text": raw_text,
                "normalized_text": norm_text,
                "problem_cue": {},
                "signals": ["safety_alert"],
                "signal_scores": {"safety_alert": 1.0},
                "concept": {"concept_id": None, "concept_confidence": 0.0, "secondary_concepts": [], "abstained": True},
                "cognitive_update": {},
                "state_deltas": {},
            }
            return route, analysis

        if (
            any(g in norm_text for g in self._GIBBERISH)
            or (len(clean_text) > 5 and not re.search(r"[aeiouy]", clean_text))
            or not clean_text
        ):
            route = RouteResult(
                primary="NONSENSE",
                source="gate",
                reason="deterministic NONSENSE gate (empty / symbols / keyboard-mash)",
            )
            analysis = {
                "raw_text": raw_text,
                "normalized_text": norm_text,
                "problem_cue": {},
                "signals": ["nonsense"],
                "signal_scores": {"nonsense": 1.0},
                "concept": {"concept_id": None, "concept_confidence": 0.0, "secondary_concepts": [], "abstained": True},
                "cognitive_update": {},
                "state_deltas": {},
            }
            return route, analysis

        # -------------------------------------------------------------------
        # 2. Intent Classification
        # -------------------------------------------------------------------
        social_greetings = ["hi", "hello", "hii", "hiii", "hey", "who are you", "what is your name", "good morning", "good evening"]
        meta_phrases = ["what can you do", "help me", "how do you work", "what features do you have"]
        control_phrases = ["stop", "pause", "exit", "quit", "take a break"]

        if any(clean_text == g or clean_text.startswith(g + " ") for g in social_greetings):
            intent = "SOCIAL"
        elif any(p in norm_text for p in meta_phrases):
            intent = "META_CAPABILITY"
        elif any(p in norm_text for p in control_phrases):
            intent = "SESSION_CONTROL"
        elif any(p in norm_text for p in ["i feel sad", "i am angry", "bored"]):
            intent = "EMOTIONAL"
        else:
            intent = "LEARNING"

        # Answer attempt detection
        answer_attempt = bool(
            "=" in norm_text
            or re.search(r"\b(answer|solution|is|equals|x\s*=|y\s*=)\s*[-+]?\d+", norm_text)
        )

        # -------------------------------------------------------------------
        # 3. Concept Resolution
        # -------------------------------------------------------------------
        matched_concept = None
        secondary_concepts = []

        for pattern, cid, _name in self._CONCEPT_MAP:
            if re.search(pattern, norm_text, re.IGNORECASE):
                if matched_concept is None:
                    matched_concept = cid
                else:
                    secondary_concepts.append(cid)

        current_concept = session.get("current_concept")
        concept_id = matched_concept or current_concept
        confidence = 0.94 if matched_concept else (0.75 if current_concept else 0.0)
        abstained = matched_concept is None and current_concept is None

        # -------------------------------------------------------------------
        # 4. Cognitive Signals & Affective State Update
        # -------------------------------------------------------------------
        signals = []
        scores = {}
        cog_update = {
            "confusion": 0.0,
            "curiosity": 0.5,
            "confidence": 0.5,
            "cognitive_load": 0.5,
            "engagement": 0.6,
        }

        if any(w in norm_text for w in ["don't get", "dont understand", "confused", "what does", "why"]):
            signals.append("confusion")
            scores["confusion"] = 0.85
            cog_update["confusion"] = 0.85
            cog_update["confidence"] = 0.20

        if any(w in norm_text for w in ["hard", "difficult", "annoying", "hate math", "stuck"]):
            signals.append("frustration")
            scores["frustration"] = 0.80
            cog_update["cognitive_load"] = 0.85

        if any(w in norm_text for w in ["explain", "how to", "tell me about", "what is", "define"]):
            signals.append("curiosity")
            signals.append("example_request")
            scores["curiosity"] = 0.88
            scores["example_request"] = 0.90
            cog_update["curiosity"] = 0.88

        if answer_attempt:
            signals.append("answer_attempt")
            scores["answer_attempt"] = 0.95
            cog_update["engagement"] = 0.90

        if not signals:
            signals.append("curiosity")
            scores["curiosity"] = 0.70

        route = RouteResult(
            primary=intent,
            concept_id=concept_id,
            concept_confidence=confidence,
            secondary_concepts=secondary_concepts,
            source="perception_classifier",
            answer_attempt=answer_attempt,
            safety_alert=False,
            uncertain=False,
            signal_scores=scores,
        )

        analysis = {
            "raw_text": raw_text,
            "normalized_text": norm_text,
            "problem_cue": {},
            "signals": signals,
            "signal_scores": scores,
            "concept": {
                "concept_id": concept_id,
                "concept_confidence": confidence,
                "secondary_concepts": secondary_concepts,
                "abstained": abstained,
                "resolution_reason": f"Matched concept: {concept_id}" if matched_concept else "Inherited session concept",
            },
            "cognitive_update": cog_update,
            "state_deltas": {
                "global": {k: v for k, v in cog_update.items() if k in ["confidence", "curiosity", "cognitive_load", "engagement"]},
                "concept_id": concept_id,
                "concept_flags": [],
                "signals": signals,
            },
        }

        return route, analysis

    def observe(
        self, text: str, session: Mapping[str, Any], current_concept: str | None
    ) -> tuple[RouteResult, Mapping[str, Any]]:
        return self.perceive_input(text, session)


def run_perception_test():
    engine = PerceptionEngine()
    perception_module = Perception(engine)

    session = {
        "current_concept": "jemh104__quadratic_equation_definition",
        "mode": "EXPLAIN",
        "context": [],
    }
    learner_state = {
        "global": {
            "confidence": 0.5,
            "curiosity": 0.5,
            "cognitive_load": 0.5,
            "engagement": 0.5,
        },
        "global_observations": {},
    }

    turn_counter = 1

    print("=" * 75)
    print("   DIRECT PHASE 2 MODULE TESTER (perception.py)")
    print("=" * 75)
    print("File Running     : Layer_Testing_files/perception.py")
    print("Execution Target : Direct Perception.perceive() method invocation")
    print("Default Concept  : jemh104__quadratic_equation_definition")
    print("\nType your student input below and press Enter (or 'exit' / 'quit' to stop).")
    print("-" * 75)

    while True:
        try:
            user_input = input(f"\n[perception.py Turn {turn_counter} Input] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("Exiting perception.py direct tester.")
            break

        turn_input = TurnInput(
            turn_id=f"turn-{turn_counter}",
            learner_id="learner-1",
            interaction={"text": user_input, "answer_budget": {"max_words": 25}},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
            trusted_observations={"stt_confidence": 1.0},
        )

        request = PerceptionRequest(
            turn_input=turn_input,
            session=dict(session),
            learner_state=dict(learner_state),
        )

        outcome = perception_module.perceive(request)
        obs: PerceptionObservation = outcome.value

        print("\n" + "=" * 70)
        print(f"    DIRECT OUTPUT FROM Perception.perceive() (Turn {turn_counter})")
        print("=" * 70)
        print(f"[*] Class & Method   : Perception.perceive()")
        print(f"[*] Spoken Intent    : {obs.intent} (Source: {obs.source})")
        print(f"[*] Concept ID       : {obs.concept_id or 'None'} (Confidence: {obs.concept_confidence:.2f})")
        print(f"[*] Secondary Concepts: {list(obs.secondary_concepts)}")
        print(f"[*] Cognitive Signals : {list(obs.signals)}")
        print(f"[*] Signal Scores    : {dict(obs.signal_scores)}")
        print(f"[*] Cognitive Update : {dict(obs.cognitive_update)}")
        print(f"[*] Safety Alert     : {obs.safety_alert}")
        print(f"[*] Answer Attempt    : {obs.answer_attempt}")
        print(f"[*] Uncertain        : {obs.uncertain}")

        if outcome.state_changes:
            print(f"\n[*] State Changes ({len(outcome.state_changes)} registered):")
            for sc in outcome.state_changes:
                print(f"     - Path {sc.path}: {sc.value}")

        if obs.source == "gate":
            print("\n[STOP] [FAST-PATH GATE EXIT IN PHASE 2 (PERCEPTION)]")
            print("Outcome         : COMPLETED_IN_PHASE_2 (Deterministic Gate Fired)")
        else:
            print("\n[NEXT] [HANDOFF TO PHASE 3 (ASSESSMENT & STATE PROJECTION)]")
            print("Outcome         : ADMITTED_TO_PHASE_3 (Phase 2 Perception Complete -> Passed into 3rd Layer)")

        print("=" * 70)

        # Update session concept if perception identified a new active concept
        if obs.concept_id:
            session["current_concept"] = obs.concept_id

        turn_counter += 1


if __name__ == "__main__":
    run_perception_test()
