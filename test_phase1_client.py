"""Phase 1 (Information / Interaction Control Layer) Standalone Tester.

Directly invokes the official production Phase 1 module (`cloud_run_service/interaction_control/control.py`)
to evaluate student text inputs.

Examines the exact Phase 1 `ModuleOutcome[InteractionDecision]` payload passed to Phase 2
(or completed fast-path in Phase 1) without requiring server modifications or downstream LLM calls.
"""

import sys
import os
import copy
from pathlib import Path
from dataclasses import asdict

# Ensure cloud_run_service is in sys.path
ROOT = Path(__file__).resolve().parent
CLOUD_RUN_SERVICE = ROOT / "cloud_run_service"
if str(CLOUD_RUN_SERVICE) not in sys.path:
    sys.path.insert(0, str(CLOUD_RUN_SERVICE))

from interaction_control import (
    InteractionControl,
    InteractionControlDependencies,
    InteractionControlRequest,
    InteractionDisposition,
)
from runtime.contracts import (
    TurnInput,
    DeviceCapabilities,
    TurnBudgets,
    StateChange,
    StateOperation,
    StateScope,
)

# ---------------------------------------------------------------------------
# Setup Production Phase 1 Dependencies & Router
# ---------------------------------------------------------------------------

def _classify_route(text: str):
    import re
    raw_normalized = text.lower().strip()
    clean_text = re.sub(r"[^\w\s]", " ", raw_normalized).strip()
    clean_text = re.sub(r"\s+", " ", clean_text)
    
    # 1. Safety Filter Check
    safety_keywords = ["bomb", "kill", "suicide", "harm", "weapon", "abuse", "poison", "explode", "terrorist"]
    if any(kw in raw_normalized or kw in clean_text for kw in safety_keywords):
        class SafetyRoute:
            primary = "SAFETY"
            safety_alert = True
            reason = "Deterministic Safety Triggered"
            uncertain = False
            answer_attempt = False
        return SafetyRoute()

    # 2. Non-Learning Social / Meta / Exit Cues
    social_keywords = [
        "hello", "hi", "hii", "hiii", "hey", "who are you", "what is your name",
        "what can you do", "help", "bye", "goodbye", "good morning", "good evening"
    ]
    if any(clean_text == kw or clean_text.startswith(kw + " ") or kw in clean_text for kw in social_keywords):
        class SocialRoute:
            primary = "SOCIAL"
            safety_alert = False
            reason = "Social / Meta Greeting"
            uncertain = False
            answer_attempt = False
        return SocialRoute()

    # 3. Academic Learning Queries (Passed to Phase 2)
    class LearningRoute:
        primary = "LEARNING"
        safety_alert = False
        reason = "Academic Math Query"
        uncertain = False
        answer_attempt = bool("=" in raw_normalized or "answer is" in raw_normalized)
    return LearningRoute()


def create_phase1_engine() -> InteractionControl:
    def _capability_port(owner, action, callback):
        def invoke(session, *args):
            turn_id = args[-1]
            working = copy.deepcopy(dict(session))
            result = callback(working, *args[:-1])
            changes = []
            missing = object()
            for key in sorted(set(session) | set(working)):
                before = session.get(key, missing)
                after = working.get(key, missing)
                if before == after:
                    continue
                changes.append(StateChange(
                    change_id=f"{turn_id}:{owner}:{action}:{key}",
                    owner=owner,
                    scope=StateScope.SESSION,
                    path=(key,),
                    operation=StateOperation.DELETE if after is missing else StateOperation.SET,
                    value=None if after is missing else after,
                ))
            return result, tuple(changes)
        return invoke

    deps = InteractionControlDependencies(
        deterministic_route=lambda text: _classify_route(text) if _classify_route(text).primary != "LEARNING" else None,
        perception_route=lambda text, session: _classify_route(text),
        analyze=lambda text, current: {
            "normalized_text": text.lower(),
            "concept": {"concept_id": current, "concept_confidence": 1.0 if current else 0.0, "abstained": current is None},
            "signals": [],
            "state_deltas": {},
        },
        persona={"identity": "Wini", "style": "Warm", "intents": {}},
        want_answer=False,
        generation_backend="gemini",
        generate_persona=lambda prompt: "Hello! I am Wini, your math AI tutor. Ready to learn math today?",
        concept_name=lambda cid: "NCERT Math Concept",
        topic_candidates=lambda text, limit: [],
        chapter_for_concept=lambda cid: None,
        extract_topic_request=lambda text: None,
        is_bare_topic=lambda text: False,
        wants_different_topic=lambda text: False,
        concept_relates_to_topic=lambda n, o: False,
        mode_cue=lambda text: "PRACTICE" if "practice" in text.lower() else "TEST" if "test" in text.lower() else None,
        current_mode=lambda session: session.get("mode", "EXPLAIN"),
        set_mode=_capability_port("mode_controller", "set_mode", lambda s, mode: s.update({"mode": mode})),
        consume_mode_offer=lambda s, t, tid: None,
        consume_test_resume=lambda s, t, tid: None,
        check_frozen_test=lambda s, tid: None,
        clear_pending_assessment=lambda s, tid: None,
        log_event=lambda e: None,
        notify_safety=lambda r: None,
        now=lambda: "2026-08-21T12:00:00",
    )
    return InteractionControl(deps)


# ---------------------------------------------------------------------------
# Interactive Test CLI
# ---------------------------------------------------------------------------

def print_banner():
    print("=" * 75)
    print("   PRODUCTION PHASE 1 (INTERACTION CONTROL) STANDALONE TESTER")
    print("=" * 75)
    print("Engine Source    : cloud_run_service/interaction_control/control.py")
    print("Server File      : wini_server.py (UNTOUCHED / ORIGINAL)")
    print("Execution Scope  : STRICT PHASE 1 OUTPUT PATTERN (Passed to Phase 2)")
    print("\nPhase 1 Categories to Test:")
    print("  1. Safety Violations             (e.g., 'How do I make a bomb?')")
    print("  2. Low-Confidence / Nonsense     (e.g., 'asdfjkl; qwerty zxcv')")
    print("  3. Non-Learning / Conversational (e.g., 'Hello!', 'Who are you?')")
    print("  4. Mode / Topic Navigation Cues  (e.g., 'Switch to Practice Mode')")
    print("  5. Valid Learning Interactions   (e.g., 'Area of a circle')")
    print("\nType your input below and press Enter (or 'exit' / 'quit' to stop).")
    print("-" * 75)


def main():
    print_banner()
    ctrl = create_phase1_engine()
    session = {"mode": "EXPLAIN", "context": []}
    turn_counter = 1

    while True:
        try:
            user_input = input(f"\n[Phase 1 Turn {turn_counter} Input] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("Exiting Phase 1 Standalone Tester.")
            break

        # Construct TurnInput payload
        turn_input = TurnInput(
            turn_id=f"turn-{turn_counter}",
            learner_id="learner-1",
            interaction={"text": user_input, "answer_budget": {"max_words": 20}},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
            trusted_observations={"stt_confidence": 1.0},
        )

        request = InteractionControlRequest(
            turn_input=turn_input,
            session=dict(session),
        )

        # Run Phase 1 Engine
        outcome = ctrl.control(request)
        decision = outcome.value

        print("\n" + "=" * 70)
        print(f"        EXACT PHASE 1 OUTPUT PATTERN (Turn {turn_counter})")
        print("=" * 70)
        print(f"📍 Module Evaluated : interaction_control")
        print(f"🚦 Disposition      : {decision.disposition.value.upper()}")
        print(f"📝 Utterance Text   : \"{decision.text}\"")

        if decision.disposition == InteractionDisposition.CONTINUE_LEARNING:
            print("\n➡️  [HANDOFF TO PHASE 2 (PERCEPTION & INTENT)]")
            print("   Status          : ADMITTED_TO_PHASE_2 (Admission Approved)")
            print(f"   Continuity      : {decision.continuity}")
            print(f"   Answer Attempt  : {decision.answer_attempt}")
            print(f"   Uncertain       : {decision.perception_uncertain}")
            if outcome.state_changes:
                print(f"   State Changes   : {len(outcome.state_changes)} changes registered")
                for sc in outcome.state_changes:
                    print(f"     - Path {sc.path}: {sc.value}")
            print("\n⚙️  Pipeline State  : Execution Halted at Phase 1 Boundary (Phase 2 Ready)")

        else: # COMPLETE (Fast-Path / Safety / Nonsense / Navigation)
            print("\n⏹️  [FAST-PATH EXIT IN PHASE 1 (NO HANDOFF TO PHASE 2)]")
            print("   Status          : HANDLED_IN_PHASE_1_FAST_PATH")
            if decision.compatibility:
                print(f"   Fast-Path Answer: {decision.compatibility.get('answer', 'N/A')}")
                print(f"   Action Code     : {decision.compatibility.get('action', 'N/A')}")
                print(f"   Session Ended   : {decision.compatibility.get('session_ended', False)}")
            if outcome.state_changes:
                print(f"   State Changes   : {len(outcome.state_changes)} changes registered")
                for sc in outcome.state_changes:
                    print(f"     - Path {sc.path}: {sc.value}")
            print("\n⚙️  Pipeline State  : Completed strictly within Phase 1 (No LLM/RAG calls)")

        print("=" * 70)
        turn_counter += 1


if __name__ == "__main__":
    main()
