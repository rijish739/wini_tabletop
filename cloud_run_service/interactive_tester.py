"""Interactive CLI tester for Phase 1 (Interaction Control) and the Input Layer.

Allows manual testing in PowerShell: type raw student input and view
session control, disposition (CONTINUE_LEARNING vs COMPLETE fast-path),
observation readings, and handoff payloads.

Ticket 11: rewritten against the typed door (UtteranceIntake) only.
The private safety keyword list and InputProcessor calls have been deleted;
safety now routes through the production gate() / lexicon path in UtteranceIntake.
"""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from typing import Any

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
    Utterance,
    UtteranceProvenance,
    UtteranceSource,
)
from utterance_intake import (
    ConfidenceFloorPolicy,
    UtteranceIntake,
    UtteranceIntakeRequest,
)


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


def _make_intake() -> UtteranceIntake:
    return UtteranceIntake(transcript_policy=ConfidenceFloorPolicy())


def _make_utterance(text: str, turn_id: str) -> Utterance:
    return Utterance(
        text=text,
        source=UtteranceSource.TYPED,
        provenance=UtteranceProvenance(
            utterance_id=turn_id,
            captured_at=datetime.now(timezone.utc).isoformat(),
            recognizer=None,
        ),
    )


def main() -> None:
    intake = _make_intake()

    deps = InteractionControlDependencies(
        deterministic_route=lambda text: None,
        perception_route=lambda text, session: None,
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
                "SAFETY": {"scripted": "Safety Alert: This request violates safety policies."},
                "SOCIAL": {"scripted": "Hello! I'm Wini, your math AI tutor. Ready to study math today?"},
                "META_CAPABILITY": {"scripted": "I can teach NCERT math concepts step-by-step."},
                "NONSENSE": {"scripted": "I didn't quite catch that. Could you please repeat?"},
                "SESSION_CONTROL": {"scripted": "Okay, stopping the session for now."},
            }
        },
        want_answer=True,
        generation_backend="gemini",
        generate_persona=lambda prompt: "Hello! I am Wini, your math AI tutor.",
        concept_name=lambda cid: "NCERT Math Concept",
        topic_candidates=lambda text, limit: [],
        chapter_for_concept=lambda cid: None,
        wants_different_topic=lambda text: False,
        mode_cue=lambda obs: getattr(obs, "session_control_mode", None),
        current_mode=lambda session: session.get("mode", "EXPLAIN"),
        set_mode=_capability_port("mode_controller", "set_mode", lambda s, mode: s.update({"mode": mode})),
        consume_mode_offer=lambda s, t, tid: None,
        consume_test_resume=lambda s, t, tid: None,
        check_frozen_test=lambda s, tid: None,
        clear_pending_assessment=lambda s, tid: None,
        log_event=lambda e: None,
        notify_safety=lambda r: None,
        now=lambda: datetime.now(timezone.utc).isoformat(),
    )

    ctrl = InteractionControl(deps)
    session: dict[str, Any] = {"mode": "EXPLAIN", "context": []}
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

        turn_id = f"turn-{turn_counter}"
        utterance = _make_utterance(user_input, turn_id)

        turn_input = TurnInput(
            turn_id=turn_id,
            learner_id="learner-1",
            interaction={"answer_budget": {"max_words": 20}},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
            utterance=utterance,
        )

        # Run UtteranceIntake to get the typed observation.
        observation = intake.observe(UtteranceIntakeRequest(turn_input=turn_input)).value

        request = InteractionControlRequest(
            turn_input=turn_input,
            session=dict(session),
            observation=observation,
        )

        outcome = ctrl.control(request)
        decision = outcome.value

        print("\n" + "=" * 70)
        print(f"[1] UTTERANCE INTAKE (UtteranceObservation)")
        print("=" * 70)
        print(f"   Raw Text            : \"{utterance.text}\"")
        print(f"   Normalized Text     : \"{observation.normalized_text}\"")
        print(f"   Authorization       : {observation.authorization.value}")
        print(f"   Safety Tripped      : {observation.safety.tripped}")
        print(f"   Illegible           : {observation.legibility.illegible}")
        print(f"   Is Problem          : {observation.problem.is_problem}")
        print(f"   Has Anaphora        : {observation.reference.has_anaphora}")
        print(f"   Parse Outcome       : {observation.transcript.parse.outcome.value}")

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
                    if sc.scope is StateScope.SESSION and len(sc.path) == 1:
                        if sc.operation is StateOperation.SET:
                            session[sc.path[0]] = sc.value
                        elif sc.operation is StateOperation.DELETE:
                            session.pop(sc.path[0], None)
            print("\n*** Outcome: ADMITTED_TO_PHASE_2")
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
            print("\n*** Outcome: COMPLETED_IN_PHASE_1")

        print("-" * 70)
        turn_counter += 1


if __name__ == "__main__":
    main()
