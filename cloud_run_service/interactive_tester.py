"""Interactive CLI tester for Phase 1 (Interaction Control) and the Input Layer.

Allows manual testing in PowerShell: type raw student input and view
session control, disposition (CONTINUE_LEARNING vs COMPLETE fast-path),
surface cues, state changes, and handoff payloads.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from typing import Any

from cognitive_input_processor.input_processor import build_default_input_processor
from interaction_control import (
    InteractionControl,
    InteractionControlDependencies,
    InteractionControlRequest,
    InteractionDisposition,
)
from runtime.contracts import (
    DeviceCapabilities,
    StateChange,
    StateOperation,
    StateScope,
    TurnBudgets,
    TurnInput,
)


def _classify_route(text: str):
    raw_normalized = text.lower().strip()
    clean_text = re.sub(r"[^\w\s]", "", raw_normalized).strip()

    # Safety Check
    safety_keywords = ["bomb", "kill", "die", "suicide", "hurt myself", "poison", "weapon", "abuse", "hate"]
    if any(k in raw_normalized for k in safety_keywords):
        class SafetyRoute:
            primary = "SAFETY"
            safety_alert = True
            safety_tier = 1
            safety_category = "HARMFUL_CONTENT"
            reason = "Deterministic Safety Triggered"
            uncertain = False
            answer_attempt = False
        return SafetyRoute()

    # Low-Confidence / Nonsense Quality Check
    gibberish_patterns = ["asdf", "qwerty", "zxcv", "12345", ";;;", "hjkl", "tgbjk"]
    if any(g in raw_normalized for g in gibberish_patterns) or (len(clean_text) > 6 and not re.search(r"[aeiouy]", clean_text)):
        class NonsenseRoute:
            primary = "NONSENSE"
            safety_alert = False
            reason = "Low-Confidence / Nonsense Quality Gate"
            uncertain = False
            answer_attempt = False
        return NonsenseRoute()

    # Social / Meta / Exit Check
    social_keywords = [
        r"\bhello\b", r"\bhi\b", r"\bhii+\b", r"\bhey\b",
        r"\bwho are you\b", r"\bwhat is your name\b", r"\bwhat can you do\b",
        r"\bhelp\b", r"\bbye\b", r"\bgoodbye\b", r"\bgood morning\b", r"\bgood evening\b",
    ]
    if any(re.search(pat, raw_normalized) for pat in social_keywords):
        class SocialRoute:
            primary = "SOCIAL"
            safety_alert = False
            reason = "Social / Meta Greeting"
            uncertain = False
            answer_attempt = False
        return SocialRoute()

    # Academic Learning Query
    class LearningRoute:
        primary = "LEARNING"
        safety_alert = False
        reason = "Academic Math Query"
        uncertain = False
        answer_attempt = bool("=" in raw_normalized or "answer is" in raw_normalized)
    return LearningRoute()


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


def main() -> None:
    processor = build_default_input_processor()

    deps = InteractionControlDependencies(
        deterministic_route=lambda text: _classify_route(text) if _classify_route(text).primary != "LEARNING" else None,
        perception_route=lambda text, session: _classify_route(text),
        analyze=lambda text, current: {
            "normalized_text": text.lower(),
            "concept": {"concept_id": current, "concept_confidence": 1.0 if current else 0.0, "abstained": current is None},
            "signals": [],
            "state_deltas": {},
        },
        persona={
            "identity": "Wini",
            "style": "Warm",
            "intents": {
                "SAFETY": {"scripted": "Safety Alert: This request violates safety policies and has been blocked by Phase 1."},
                "SOCIAL": {"scripted": "Hello! I'm Wini, your math AI tutor. Ready to study math today?"},
                "META_CAPABILITY": {"scripted": "I can teach NCERT math concepts, solve math problems step-by-step, and offer practice exercises."},
                "NONSENSE": {"scripted": "I didn't quite catch that. Could you please repeat your question?"},
                "SESSION_CONTROL": {"scripted": "Okay, stopping the session for now. Let me know when you want to learn again!"},
            }
        },
        want_answer=True,
        generation_backend="gemini",
        generate_persona=lambda prompt: "Hello! I am Wini, your math AI tutor. Ready to study math today?",
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
        now=lambda: "2026-08-25T12:00:00",
    )

    ctrl = InteractionControl(deps)
    session = {"mode": "EXPLAIN", "context": []}
    turn_counter = 1

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 75)
    print("   WINI TUTOR: INTERACTIVE INPUT & INTERACTION CONTROL TESTER")
    print("=" * 75)
    print("Type your input below and press Enter (or 'exit' / 'quit' to stop).")
    print("-" * 75)

    while True:
        try:
            user_input = input(f"\n[Turn {turn_counter} Input] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("Exiting interactive tester.")
            break

        # 1. Test Input Layer Ingestion (both ingest and process)
        ingested = processor.ingest(user_input, context=session.get("context"))
        processed = processor.process(user_input, session_context=session)

        # 2. Test Interaction Control Turn
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

        outcome = ctrl.control(request)
        decision = outcome.value

        print("\n" + "=" * 70)
        print(f"[1] INPUT LAYER FULL OBSERVATION (InputProcessor)")
        print("=" * 70)
        print(f"   Raw Text            : \"{processed.raw_text}\"")
        print(f"   Normalized Text     : \"{processed.normalized_text}\"")
        print(f"   Tokens              : {processed.tokens}")
        print(f"   Problem Cue         : {ingested.problem_cue}")
        print(f"   Surface Cues        : {ingested.surface_cues}")
        print(f"   Candidate Concepts  : {processed.candidate_concepts}")
        print(f"   Metadata            : {processed.metadata}")
        print(f"   Heuristic Signals   :")
        for sig, val in processed.signals.__dict__.items():
            if val > 0.0:
                print(f"     * {sig:20s}: {val:.2f}")

        print("\n" + "=" * 70)
        print(f"[2] INTERACTION & SESSION CONTROL (Phase 1)")
        print("=" * 70)
        print(f"   Disposition         : {decision.disposition.value.upper()}")
        print(f"   Current Session Mode: {session.get('mode', 'EXPLAIN')}")
        print(f"   Student Text        : \"{decision.text}\"")

        if decision.disposition == InteractionDisposition.CONTINUE_LEARNING:
            print("\n--> [HANDOFF TO PHASE 2 (PERCEPTION & INTENT)]")
            print(f"   Continuity          : {decision.continuity}")
            print(f"   Answer Attempt      : {decision.answer_attempt}")
            print(f"   Perception Uncertain: {decision.perception_uncertain}")
            if outcome.state_changes:
                print(f"   State Changes       : {len(outcome.state_changes)} registered")
                for sc in outcome.state_changes:
                    print(f"     - {sc.scope.value}.{sc.path}: {sc.value}")
                    # Apply session state changes locally
                    if sc.scope is StateScope.SESSION and len(sc.path) == 1:
                        if sc.operation is StateOperation.SET:
                            session[sc.path[0]] = sc.value
                        elif sc.operation is StateOperation.DELETE:
                            session.pop(sc.path[0], None)
            print("\n*** Outcome: ADMITTED_TO_PHASE_2 (Proceeds to Learning & Concept Resolution)")

        else:
            print("\n<-- [FAST-PATH / SESSION CONTROL EXIT IN PHASE 1]")
            if decision.compatibility:
                print(f"   Action Code         : {decision.compatibility.get('action', 'N/A')}")
                print(f"   Fast-Path Answer    : {decision.compatibility.get('answer', 'N/A')}")
            if outcome.state_changes:
                print(f"   State Changes       : {len(outcome.state_changes)} registered")
                for sc in outcome.state_changes:
                    print(f"     - {sc.scope.value}.{sc.path}: {sc.value}")
                    if sc.scope is StateScope.SESSION and len(sc.path) == 1:
                        if sc.operation is StateOperation.SET:
                            session[sc.path[0]] = sc.value
                        elif sc.operation is StateOperation.DELETE:
                            session.pop(sc.path[0], None)
            print("\n*** Outcome: COMPLETED_IN_PHASE_1 (No downstream LLM / state mutation)")

        print("-" * 70)
        turn_counter += 1


if __name__ == "__main__":
    main()
