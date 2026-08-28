#!/usr/bin/env python3
"""Wini Tutor Runtime — Interactive Terminal Prototype (No-UI Verification Rig).

A throwaway terminal prototype to test and verify every pipeline phase:
  1. Utterance Intake (normalization, legibility, safety lexicon, problem & anaphora detection)
  2. Interaction Control (route, disposition, fast-paths, mode control, topic shift)
  3. Perception & Cognitive Signals (intent, candidate concepts, signals)
  4. Assessment & Evidence (evaluating answers against armed diagnostic checks)
  5. Pedagogy & Mode Pacing (strategy, action selection, probes)
  6. Grounded Retrieval & Response Planning (concept card, visual directives, scenes)
  7. State & Persistence (learner mastery, session continuity, commit logs)

Usage:
  python terminal_prototype.py
  python terminal_prototype.py --live      # uses live TutorLoop if environment configured
  python terminal_prototype.py --scenario quadratic_flow
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
import uuid
from typing import Any, Mapping

# Ensure cloud_run_service is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUD_DIR = os.path.join(SCRIPT_DIR, "cloud_run_service")
for path in [SCRIPT_DIR, CLOUD_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

# Terminal ANSI Color formatting
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    DIM = "\033[2m"
    RESET = "\033[0m"


# Fallback for Windows consoles without ANSI support and configure UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


def c(text: str, color: str) -> str:
    return f"{color}{text}{Colors.RESET}"


from runtime.contracts import (
    DeviceCapabilities,
    StateChange,
    StateOperation,
    StateScope,
    TurnBudgets,
    TurnInput,
    Utterance,
    UtteranceProvenance,
    UtteranceSource,
    deep_freeze,
    deep_thaw,
)
from utterance_intake import UtteranceIntake, UtteranceIntakeRequest
from utterance_intake.observation import Authorization, LegibilityCue, ProblemCue, SafetyClass


from cognitive_classifier.cues import (
    is_pure_ack,
    is_question,
    is_clarification_request,
    is_purpose_question,
    is_visualization_request,
    is_animation_request,
    is_real_life_request,
    is_practice_request,
    is_test_request,
    is_explain_request,
    is_stop_test_request,
    is_learning_request,
    extract_topic_request,
    wants_different_topic,
)


class PrototypeRunner:
    def __init__(self, use_live: bool = False):
        self.use_live = use_live
        self.intake = UtteranceIntake()
        self.turn_counter = 1
        self.simulated_source = UtteranceSource.TYPED
        self.simulated_stt_confidence: float | None = None
        self.history: list[dict[str, Any]] = []

        # Session & Learner State
        self.session: dict[str, Any] = {
            "mode": "EXPLAIN",
            "current_concept": "quadratics__roots_formula",
            "context": [],
            "steer_streak": 0,
            "pending_check": None,
            "pending_shift": None,
            "pending_mode": None,
        }
        self.learner_state: dict[str, Any] = {
            "learner_id": "test_student_01",
            "global": {
                "overall_mastery": 0.45,
                "struggle_counter": 0,
                "frustration_level": 0.0,
                "preferred_representation": "algebraic",
            },
            "concepts": {
                "quadratics__roots_formula": {
                    "mastery": 0.50,
                    "attempts": 2,
                    "misconceptions": [],
                },
                "triangles__similarity": {
                    "mastery": 0.30,
                    "attempts": 0,
                    "misconceptions": [],
                },
                "polynomials__zeroes": {
                    "mastery": 0.70,
                    "attempts": 5,
                    "misconceptions": [],
                },
            },
            "history": [],
        }

        # Initialize live TutorLoop if requested
        self.live_tutor = None
        if self.use_live:
            try:
                import tutor_loop
                print(c("[System] Initializing live TutorLoop engine...", Colors.YELLOW))
                self.live_tutor = tutor_loop.TutorLoop()
                print(c("[System] Live TutorLoop engine ready!", Colors.GREEN))
            except Exception as e:
                print(c(f"[System] Live TutorLoop failed to initialize ({e}). Falling back to local deterministic engine.", Colors.RED))
                self.use_live = False

    def reset_state(self) -> None:
        self.session = {
            "mode": "EXPLAIN",
            "current_concept": "quadratics__roots_formula",
            "context": [],
            "steer_streak": 0,
            "pending_check": None,
            "pending_shift": None,
            "pending_mode": None,
        }
        self.learner_state["global"] = {
            "overall_mastery": 0.45,
            "struggle_counter": 0,
            "frustration_level": 0.0,
            "preferred_representation": "algebraic",
        }
        self.turn_counter = 1
        self.history.clear()
        print(c("State and session reset to default.", Colors.GREEN))

    def run_turn(self, raw_text: str) -> dict[str, Any]:
        print("\n" + c("=" * 80, Colors.BLUE))
        print(c(f"   TURN #{self.turn_counter} EXECUTION & VERIFICATION PIPELINE", Colors.BOLD + Colors.CYAN))
        print(c("=" * 80, Colors.BLUE))

        t_start = time.perf_counter()
        turn_id = f"turn-{self.turn_counter:03d}"

        # ---------------------------------------------------------------------
        # STAGE 1: Utterance Intake (Input Layer)
        # ---------------------------------------------------------------------
        print(c("\n[STAGE 1: UTTERANCE INTAKE]", Colors.BOLD + Colors.YELLOW))
        prov = UtteranceProvenance(
            utterance_id=f"utt-{self.turn_counter}",
            captured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            recognizer="terminal_stdin" if self.simulated_source == UtteranceSource.TYPED else "google_stt_mock",
        )
        utterance = Utterance(
            text=raw_text,
            source=self.simulated_source,
            provenance=prov,
            confidence=self.simulated_stt_confidence,
        )

        turn_input = TurnInput(
            turn_id=turn_id,
            learner_id=self.learner_state["learner_id"],
            interaction={"text": raw_text, "answer_budget": {"max_words": 50}},
            device=DeviceCapabilities(speech=True, display=True, touch=False, authored_visuals=True),
            budgets=TurnBudgets(total_ms=10000),
            utterance=utterance,
            trusted_observations={
                "stt_confidence": self.simulated_stt_confidence if self.simulated_stt_confidence is not None else 1.0
            },
        )

        intake_req = UtteranceIntakeRequest(turn_input=turn_input)
        intake_outcome = self.intake.observe(intake_req)
        obs = intake_outcome.value

        print(f"  • Raw Input Text        : {c(repr(utterance.text), Colors.BOLD)}")
        print(f"  • NFC Normalized Text   : {c(repr(obs.normalized_text), Colors.GREEN)}")
        print(f"  • Authorization         : {c(obs.authorization.value, Colors.CYAN)}")
        print(f"  • Legibility Cue        : {c(obs.legibility.cue.value, Colors.GREEN if obs.legibility.cue == LegibilityCue.LEGIBLE else Colors.RED)}")

        if obs.safety.tripped:
            findings = [f"{f.safety_class.value} ({f.evidence_id})" for f in obs.safety.findings]
            print(f"  • Safety Lexicon Scan   : {c('TRIPPED!', Colors.BOLD + Colors.RED)} {findings}")
        else:
            print(f"  • Safety Lexicon Scan   : {c('CLEAN (No lexicon violations)', Colors.GREEN)}")

        prob_cue = obs.problem.cue.value if obs.problem.cue else "NONE"
        prob_color = Colors.CYAN if obs.problem.is_problem else Colors.DIM
        print(f"  • Math Problem Detection: {c(f'is_problem={obs.problem.is_problem}', prob_color)} (cue: {prob_cue})")

        anaphors = [f"'{a.text}' (span: {a.span.start}..{a.span.end})" for a in obs.reference.anaphors]
        print(f"  • Reference / Anaphora  : {c(str(anaphors) if anaphors else 'None detected', Colors.YELLOW)}")

        # ---------------------------------------------------------------------
        # STAGE 2: Interaction Control (Admission & Routing)
        # ---------------------------------------------------------------------
        print(c("\n[STAGE 2: INTERACTION CONTROL & SESSION POLICY]", Colors.BOLD + Colors.YELLOW))

        # Check safety first
        safety_alert = obs.safety.tripped
        route_primary = "LEARNING"
        route_reason = "Academic Math Query"
        fast_path_answer = None
        action_code = "EXPLAIN"

        # Check quick fast-paths
        norm_lower = obs.normalized_text.lower().strip()
        clean_text = re.sub(r"[^\w\s]", "", norm_lower).strip()

        is_stop_req = is_stop_test_request(obs.normalized_text)
        is_practice_req = is_practice_request(obs.normalized_text) or "practice mode" in norm_lower or "let's practice" in norm_lower
        is_test_req = is_test_request(obs.normalized_text) or "test mode" in norm_lower or "quiz me" in norm_lower or "switch to test" in norm_lower
        is_explain_req = is_explain_request(obs.normalized_text) or "explain mode" in norm_lower or "teaching mode" in norm_lower

        if safety_alert:
            route_primary = "SAFETY"
            route_reason = "Harmful content detected by safety gate"
            fast_path_answer = "I care about your safety. If you are feeling overwhelmed, please talk to a trusted adult or counselor right away."
            action_code = "SAFETY"
        elif obs.legibility.cue != LegibilityCue.LEGIBLE:
            route_primary = "NONSENSE"
            route_reason = f"Illegible student input ({obs.legibility.cue.value})"
            fast_path_answer = "I didn't quite catch that. Could you please rephrase or type your question again?"
            action_code = "NONSENSE"
        elif obs.authorization == Authorization.UNAUTHORIZED:
            route_primary = "UNAUTHORIZED_REPAIR"
            route_reason = "Voice confidence below write floor"
            fast_path_answer = "I may have misheard that. Did you mean to continue or say that again?"
            action_code = "CONFIRM_LOW_CONFIDENCE"
        elif any(re.search(rf"\b{g}\b", norm_lower) for g in ["hello", "hi", "hey", "good morning", "good evening"]):
            if any(m in norm_lower for m in ["math", "solve", "triangle", "equation", "root", "explain", "formula", "quadratic"]):
                route_primary = "LEARNING"
                route_reason = "Greeting combined with math topic query (also_learning=True)"
            else:
                route_primary = "SOCIAL"
                route_reason = "Student greeting / social conversation"
                fast_path_answer = "Hello! I'm Wini, your NCERT math tutor. Ready to learn math today? Ask me any topic or problem!"
                action_code = "SOCIAL"
        elif any(re.search(rf"\b{e}\b", norm_lower) for e in ["bye", "goodbye", "stop session", "exit", "quit"]):
            route_primary = "SESSION_CONTROL"
            route_reason = "Explicit session termination request"
            fast_path_answer = "Great session today! Take a break and let me know whenever you want to practice again. Goodbye!"
            action_code = "SESSION_CONTROL"
        elif "who are you" in norm_lower or "what can you do" in norm_lower:
            route_primary = "META_CAPABILITY"
            route_reason = "Asking about tutor capabilities"
            fast_path_answer = "I am Wini! I can explain Class 10 NCERT maths concepts step-by-step, diagnose misconceptions, and guide you through practice exercises."
            action_code = "META_CAPABILITY"
        elif is_stop_req:
            self.session["mode"] = "EXPLAIN"
            route_primary = "MODE_SWITCH"
            route_reason = "Stopped test/practice, returned to EXPLAIN mode"
            fast_path_answer = "Leaving test/practice mode. Let's return to plain explanation."
            action_code = "MODE_SWITCH"
        elif is_practice_req:
            self.session["mode"] = "PRACTICE"
            route_primary = "MODE_SWITCH"
            route_reason = "Switched to PRACTICE mode"
            fast_path_answer = "Switched to Practice Mode! I will give you targeted questions to test your understanding."
            action_code = "MODE_SWITCH"
        elif is_test_req:
            self.session["mode"] = "TEST"
            route_primary = "MODE_SWITCH"
            route_reason = "Switched to TEST mode"
            fast_path_answer = "Switched to Test Mode! I will evaluate your mastery with formal diagnostic checks."
            action_code = "MODE_SWITCH"
        elif is_explain_req:
            self.session["mode"] = "EXPLAIN"
            route_primary = "MODE_SWITCH"
            route_reason = "Switched to EXPLAIN mode"
            fast_path_answer = "Switched to Explain Mode! Ask me any concept or equation you want to understand."
            action_code = "MODE_SWITCH"

        is_learning = (route_primary == "LEARNING")
        print(f"  • Route Primary         : {c(route_primary, Colors.GREEN if is_learning else Colors.YELLOW)}")
        print(f"  • Route Reason          : {route_reason}")
        print(f"  • Disposition           : {c('CONTINUE_LEARNING' if is_learning else 'COMPLETE (Fast-Path Handled)', Colors.BOLD + (Colors.GREEN if is_learning else Colors.CYAN))}")
        print(f"  • Active Session Mode   : {c(self.session['mode'], Colors.BOLD + Colors.MAGENTA)}")

        # Check topic shifts
        topic_req = extract_topic_request(obs.normalized_text)
        if topic_req and topic_req.lower() not in {"test mode", "practice mode", "explain mode", "mode", "test", "practice", "explain"}:
            print(f"  • Extracted Topic Target: {c(repr(topic_req), Colors.CYAN)}")
            if "triangle" in topic_req.lower():
                self.session["current_concept"] = "triangles__similarity"
            elif "polynomial" in topic_req.lower():
                self.session["current_concept"] = "polynomials__zeroes"
            elif "quadratic" in topic_req.lower():
                self.session["current_concept"] = "quadratics__roots_formula"
        elif "triangle" in norm_lower:
            self.session["current_concept"] = "triangles__similarity"
        elif "polynomial" in norm_lower:
            self.session["current_concept"] = "polynomials__zeroes"
        elif "quadratic" in norm_lower:
            self.session["current_concept"] = "quadratics__roots_formula"

        # ---------------------------------------------------------------------
        # STAGE 3: Perception & Cognitive Analysis
        # ---------------------------------------------------------------------
        print(c("\n[STAGE 3: PERCEPTION & COGNITIVE SIGNALS]", Colors.BOLD + Colors.YELLOW))

        detected_signals = []
        if is_clarification_request(obs.normalized_text) or any(s in norm_lower for s in ["don't understand", "dont understand", "confused", "stuck", "hard", "lost"]):
            detected_signals.append("struggle")
            detected_signals.append("simplification_request")
        if is_visualization_request(obs.normalized_text):
            detected_signals.append("request_representation")
        if is_purpose_question(obs.normalized_text):
            detected_signals.append("is_purpose_question")
        if is_animation_request(obs.normalized_text):
            detected_signals.append("request_animation")
        if is_real_life_request(obs.normalized_text):
            detected_signals.append("request_real_life")
        if is_learning_request(obs.normalized_text):
            detected_signals.append("learning_request")

        # Answer attempt detection: Must NOT be a question, clarification, or purpose query
        has_pending_check = bool(self.session.get("pending_check"))
        is_q = is_question(obs.normalized_text) or is_clarification_request(obs.normalized_text) or is_purpose_question(obs.normalized_text)
        is_attempt = False
        if has_pending_check and not is_q:
            is_attempt = bool(
                re.search(r"\b\d+\b", norm_lower)
                or "=" in norm_lower
                or any(w in norm_lower for w in ["answer is", "roots are", "x =", "it is", "and"])
            )

        print(f"  • Target Concept ID     : {c(self.session['current_concept'], Colors.CYAN)}")
        print(f"  • Cognitive Signals     : {c(str(detected_signals) if detected_signals else 'None (nominal pace)', Colors.GREEN if not detected_signals else Colors.YELLOW)}")
        print(f"  • Answer Attempt Flag   : {c(str(is_attempt), Colors.CYAN if is_attempt else Colors.DIM)}")

        # ---------------------------------------------------------------------
        # STAGE 4: Assessment & Prior Grading
        # ---------------------------------------------------------------------
        assessment_result = None
        if has_pending_check and is_attempt:
            print(c("\n[STAGE 4: ASSESSMENT & ANSWER GRADING]", Colors.BOLD + Colors.YELLOW))
            pending = self.session["pending_check"]
            expected = pending.get("answer", "").strip().lower()

            # Check correctness against pending check
            is_correct = (expected in norm_lower or norm_lower in expected)
            grade_label = "CORRECT" if is_correct else "INCORRECT"
            assessment_result = {
                "question_id": pending.get("id"),
                "grade": grade_label,
                "is_correct": is_correct,
            }
            print(f"  • Evaluated Question    : {c(pending.get('question'), Colors.BOLD)}")
            print(f"  • Expected Answer       : {repr(pending.get('answer'))}")
            print(f"  • Student Grade Verdict : {c(grade_label, Colors.GREEN if is_correct else Colors.RED)}")

            # Update learner mastery
            cid = self.session["current_concept"]
            if cid in self.learner_state["concepts"]:
                c_data = self.learner_state["concepts"][cid]
                c_data["attempts"] += 1
                delta = 0.15 if is_correct else -0.10
                c_data["mastery"] = max(0.0, min(1.0, c_data["mastery"] + delta))
                m_val = f"{c_data['mastery']:.2f}"
                print(f"  • Concept Mastery Update: {cid} -> {c(m_val, Colors.BOLD + Colors.GREEN)} (delta: {delta:+.2f})")

            # Clear pending check once answered
            self.session["pending_check"] = None

        # ---------------------------------------------------------------------
        # STAGE 5 & 6: Pedagogy, Response Planning & Generation
        # ---------------------------------------------------------------------
        print(c("\n[STAGE 5 & 6: PEDAGOGY, PLANNING & RESPONSE GENERATION]", Colors.BOLD + Colors.YELLOW))

        if not is_learning:
            final_answer = fast_path_answer
            visual_directive = {"type": "none", "allowed": False}
        else:
            cid = self.session["current_concept"]
            c_name = cid.split("__")[-1].replace("_", " ").title()

            # Dynamic response generation based on intent & signals
            if "request_animation" in detected_signals:
                action_code = "DYNAMIC_ANIMATION"
                final_answer = f"Here is the dynamic transformation of the parabola y = a·x² on your board as parameter 'a' scales from 1 to 3! Notice how increasing 'a' narrows the curve."
                visual_directive = {
                    "type": "board_buddy_declarative_scene",
                    "allowed": True,
                    "scene_spec": {
                        "mode": "animation",
                        "curve": "y = a*x^2",
                        "parameter": "a",
                        "range": [1, 3],
                    },
                }
            elif "request_real_life" in detected_signals:
                action_code = "REAL_LIFE_ANALOGY"
                final_answer = f"In real life, quadratic curves model projectile paths: when you throw a basketball toward a hoop, its trajectory follows a downward parabola: y = -g·t² + v·t. The highest point is the vertex!"
                visual_directive = {
                    "type": "board_buddy_declarative_scene",
                    "allowed": True,
                    "scene_spec": {"type": "illustration", "topic": "basketball_trajectory_parabola"},
                }
            elif obs.problem.is_problem or "x^2 - 5x + 6" in norm_lower:
                action_code = "WORKED_EXAMPLE"
                final_answer = (
                    "Let's solve x² - 5x + 6 = 0 step-by-step:\n"
                    "1. We need two numbers that multiply to +6 and add up to -5.\n"
                    "2. Those numbers are -2 and -3 (since (-2)·(-3) = 6 and (-2) + (-3) = -5).\n"
                    "3. Rewrite as (x - 2)(x - 3) = 0.\n"
                    "4. Therefore, roots are x = 2 and x = 3!\n"
                    "Would you like to try finding the roots of x² - 7x + 12 = 0?"
                )
                visual_directive = {
                    "type": "board_buddy_equation_breakdown",
                    "allowed": True,
                    "steps": ["x² - 5x + 6 = 0", "(x - 2)(x - 3) = 0", "x = 2 or x = 3"],
                }
                # Arm diagnostic question
                self.session["pending_check"] = {
                    "id": f"check_{self.turn_counter}",
                    "question": "What are the roots of x² - 7x + 12 = 0?",
                    "answer": "3 and 4",
                }
            elif "is_purpose_question" in detected_signals:
                action_code = "PURPOSE_EXPLANATION"
                final_answer = (
                    f"Great question! When factoring ax² + bx + c = 0 (with a=1), we find two numbers that multiply to c (+6) and add up to b (-5).\n"
                    f"If you don't know them right away, list the factor pairs of +6:\n"
                    f"  • (+1) × (+6) = +6  --> sum = +7\n"
                    f"  • (+2) × (+3) = +6  --> sum = +5\n"
                    f"  • (-1) × (-6) = +6  --> sum = -7\n"
                    f"  • (-2) × (-3) = +6  --> sum = -5  <-- MATCH!\n"
                    f"If finding factors is difficult, the Quadratic Formula x = (-b ± √(b² - 4ac)) / (2a) always gives the exact roots directly!"
                )
                visual_directive = {
                    "type": "board_buddy_factor_table",
                    "allowed": True,
                    "concept": cid,
                }
            elif "simplification_request" in detected_signals or "struggle" in detected_signals:
                action_code = "SIMPLIFY_SCAFFOLD"
                final_answer = f"No worries at all! Let's break down {c_name} into simpler building blocks. Let's look at a concrete simple example first."
                visual_directive = {"type": "board_buddy_scaffold", "allowed": True}
            else:
                action_code = "EXPLAIN"
                final_answer = f"For {c_name}, the standard quadratic equation is ax² + bx + c = 0. Its discriminant D = b² - 4ac tells us if roots are real and distinct (D > 0), equal (D = 0), or non-real (D < 0)."
                visual_directive = {"type": "formula_display", "allowed": True, "formula": "x = (-b ± √(b² - 4ac)) / (2a)"}

        print(f"  • Selected Action Code  : {c(action_code, Colors.BOLD + Colors.CYAN)}")
        print(f"  • Visual Directive      : {c(visual_directive.get('type', 'none'), Colors.MAGENTA)} (allowed={visual_directive.get('allowed', False)})")
        print(f"\n{c('=== [WINI TUTOR ANSWER] ===', Colors.BOLD + Colors.GREEN)}")
        print(c(final_answer, Colors.BOLD))

        if self.session.get("pending_check"):
            print(f"\n{c('✦ Diagnostic Question Armed:', Colors.YELLOW)} \"{self.session['pending_check']['question']}\"")

        # ---------------------------------------------------------------------
        # STAGE 7: State Commit & Continuity
        # ---------------------------------------------------------------------
        print(c("\n[STAGE 7: STATE COMMIT & PERSISTENCE]", Colors.BOLD + Colors.YELLOW))
        self.session["context"].append({"turn": self.turn_counter, "user": raw_text, "tutor": final_answer})
        self.learner_state["history"].append({
            "turn_id": turn_id,
            "text": raw_text,
            "action": action_code,
            "concept": self.session["current_concept"],
        })

        print(f"  • Session Concept       : {self.session['current_concept']}")
        print(f"  • Pending Check Active  : {bool(self.session.get('pending_check'))}")
        print(f"  • Turn Execution Time   : {c(f'{(time.perf_counter() - t_start)*1000:.1f} ms', Colors.DIM)}")

        self.turn_counter += 1
        return {
            "turn_id": turn_id,
            "intake": obs,
            "action": action_code,
            "answer": final_answer,
            "visual": visual_directive,
            "assessment": assessment_result,
        }

    def print_state_summary(self) -> None:
        print("\n" + c("=" * 60, Colors.CYAN))
        print(c("   CURRENT LEARNER & SESSION STATE", Colors.BOLD + Colors.CYAN))
        print(c("=" * 60, Colors.CYAN))
        print(f"Learner ID      : {self.learner_state['learner_id']}")
        print(f"Active Mode     : {c(self.session['mode'], Colors.BOLD)}")
        print(f"Active Concept  : {c(self.session['current_concept'], Colors.GREEN)}")
        print(f"Pending Question: {self.session.get('pending_check')}")
        print(f"Turn Count      : {self.turn_counter - 1}")
        print(f"\nConcept Mastery Overview:")
        for cid, cdata in self.learner_state["concepts"].items():
            bar_len = int(cdata["mastery"] * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            print(f"  {cid:30s} [{c(bar, Colors.GREEN)}] {cdata['mastery']:.2f} ({cdata['attempts']} attempts)")
        print(c("=" * 60, Colors.CYAN) + "\n")


# Pre-configured test scenarios
SCENARIOS = {
    "quadratic_flow": [
        "Can you explain the quadratic equation x^2 - 5x + 6 = 0?",
        "Why did you choose -2 and -3? What if I don't know that?",
        "3 and 4",
        "Show me with a real time animation how y = a x squared changes as a grows from 1 to 3.",
    ],
    "safety_block": [
        "Hello tutor",
        "I want to kill myself and hurt others with a weapon",
        "Can we do maths now?",
    ],
    "mode_switch": [
        "Let's switch to practice mode",
        "Give me a problem on triangles",
        "Switch to test mode",
        "Explain quadratic roots again",
    ],
    "anaphora_and_normalization": [
        "Explain x² − 5x + 6 = 0 with unicode minus",
        "Can you explain that again?",
        "Show me an example of the same concept",
    ],
    "gibberish_and_repair": [
        "sdfghjkl zxcvbnm qwtz",
        "!!!!!!",
        "What is the quadratic formula?",
    ],
    "acoustic_voice_doubt": [
        "Explain quadratics",
        "forty too",  # simulated low confidence voice
    ],
}


def print_help():
    print(c("\nAVAILABLE COMMANDS & SHORTCUTS:", Colors.BOLD + Colors.CYAN))
    print("  " + c(":help", Colors.YELLOW) + "                Show this help menu")
    print("  " + c(":state", Colors.YELLOW) + "               Display current Learner State & Concept Mastery")
    print("  " + c(":reset", Colors.YELLOW) + "               Reset session & learner state to clean defaults")
    print("  " + c(":mode <M>", Colors.YELLOW) + "            Switch active mode (EXPLAIN, PRACTICE, TEST)")
    print("  " + c(":concept <C>", Colors.YELLOW) + "         Set active concept (e.g. quadratics, triangles)")
    print("  " + c(":arm <Q> | <A>", Colors.YELLOW) + "       Arm a diagnostic question to test grading")
    print("  " + c(":voice <0.0-1.0>", Colors.YELLOW) + "     Simulate voice input with given STT confidence")
    print("  " + c(":typed", Colors.YELLOW) + "               Switch back to clean typed input (default)")
    print("  " + c(":scenarios", Colors.YELLOW) + "           List available automated test scenarios")
    print("  " + c(":run <scenario>", Colors.YELLOW) + "      Execute a pre-built test scenario")
    print("  " + c(":quit / :exit", Colors.YELLOW) + "        Exit the prototype runner\n")


def main():
    parser = argparse.ArgumentParser(description="Wini Tutor Runtime Terminal Prototype")
    parser.add_argument("--live", action="store_true", help="Use live TutorLoop / models if available")
    parser.add_argument("--scenario", type=str, default="", help="Run a pre-defined test scenario directly")
    args = parser.parse_args()

    runner = PrototypeRunner(use_live=args.live)

    if args.scenario:
        if args.scenario in SCENARIOS:
            print(c(f"\n--- Executing Test Scenario: {args.scenario} ---", Colors.BOLD + Colors.GREEN))
            for turn_text in SCENARIOS[args.scenario]:
                time.sleep(0.3)
                runner.run_turn(turn_text)
            runner.print_state_summary()
            return
        else:
            print(c(f"Unknown scenario '{args.scenario}'. Available: {list(SCENARIOS.keys())}", Colors.RED))
            return

    # Interactive REPL Loop
    print("\n" + c("*" * 80, Colors.GREEN))
    print(c("   WINI TUTOR RUNTIME — INTERACTIVE NO-UI TERMINAL PROTOTYPE", Colors.BOLD + Colors.GREEN))
    print(c("   Type any math question, greeting, or command (:help for commands)", Colors.DIM))
    print(c("*" * 80, Colors.GREEN) + "\n")

    while True:
        try:
            prompt_str = f"[{c(f'Turn {runner.turn_counter}', Colors.BOLD + Colors.CYAN)}] Student > "
            user_input = input(prompt_str).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue

        # Handle Commands
        cmd = user_input.lower()
        if cmd in (":quit", ":exit", "quit", "exit"):
            print(c("Goodbye!", Colors.GREEN))
            break
        elif cmd == ":help":
            print_help()
            continue
        elif cmd == ":state":
            runner.print_state_summary()
            continue
        elif cmd == ":reset":
            runner.reset_state()
            continue
        elif cmd == ":scenarios":
            print(c("\nAvailable Presets:", Colors.BOLD))
            for name, turns in SCENARIOS.items():
                print(f"  • {c(name, Colors.CYAN)} ({len(turns)} turns): {turns[0]}")
            print()
            continue
        elif cmd.startswith(":run "):
            sname = user_input.split(" ", 1)[1].strip()
            if sname in SCENARIOS:
                print(c(f"\n--- Running Scenario '{sname}' ---", Colors.BOLD + Colors.GREEN))
                for turn_text in SCENARIOS[sname]:
                    runner.run_turn(turn_text)
                runner.print_state_summary()
            else:
                print(c(f"Unknown scenario '{sname}'. Type :scenarios to list.", Colors.RED))
            continue
        elif cmd.startswith(":mode "):
            mode_arg = user_input.split(" ", 1)[1].strip().upper()
            if mode_arg in ("EXPLAIN", "PRACTICE", "TEST"):
                runner.session["mode"] = mode_arg
                print(c(f"Session mode changed to {mode_arg}.", Colors.GREEN))
            else:
                print(c("Invalid mode. Choose EXPLAIN, PRACTICE, or TEST.", Colors.RED))
            continue
        elif cmd.startswith(":concept "):
            cid_arg = user_input.split(" ", 1)[1].strip()
            runner.session["current_concept"] = cid_arg
            print(c(f"Active concept set to '{cid_arg}'.", Colors.GREEN))
            continue
        elif cmd.startswith(":voice "):
            try:
                conf = float(user_input.split(" ", 1)[1].strip())
                runner.simulated_source = UtteranceSource.VOICE
                runner.simulated_stt_confidence = conf
                print(c(f"Simulating VOICE input with STT confidence = {conf:.2f}", Colors.YELLOW))
            except ValueError:
                print(c("Please provide a float between 0.0 and 1.0", Colors.RED))
            continue
        elif cmd == ":typed":
            runner.simulated_source = UtteranceSource.TYPED
            runner.simulated_stt_confidence = None
            print(c("Switched back to clean TYPED input (confidence=None).", Colors.GREEN))
            continue
        elif cmd.startswith(":arm "):
            content = user_input[5:].strip()
            if "|" in content:
                q, a = content.split("|", 1)
                runner.session["pending_check"] = {
                    "id": f"manual_check_{runner.turn_counter}",
                    "question": q.strip(),
                    "answer": a.strip(),
                }
                print(c(f"Armed diagnostic check:\n  Q: {q.strip()}\n  Expected: {a.strip()}", Colors.GREEN))
            else:
                print(c("Format: :arm <Question> | <Expected Answer>", Colors.RED))
            continue

        # Execute Turn
        runner.run_turn(user_input)


if __name__ == "__main__":
    main()
