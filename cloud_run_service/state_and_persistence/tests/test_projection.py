from __future__ import annotations

import unittest

from runtime.contracts import StateChange, StateOperation, StateScope
from state_and_persistence import (
    CapabilityStateAccess,
    StateChangeConflict,
    StateChangeRejected,
    WorkingStateProjection,
)


ACCESS = {
    "pedagogy": CapabilityStateAccess(
        learner_read=(("concept_states",), ("global", "confidence")),
        session_read=(("current_concept",), ("mode",)),
        session_write=(("mode",),),
    ),
    "assessment_evidence": CapabilityStateAccess(
        learner_read=(("concept_states",), ("evidence_ledger",)),
        learner_write=(("evidence_ledger",),),
    ),
}


class WorkingStateProjectionTests(unittest.TestCase):
    def make_projection(self) -> WorkingStateProjection:
        return WorkingStateProjection(
            learner_id="learner-1",
            state={
                "concept_states": {"fractions": {"mastery": 0.4}},
                "global": {"confidence": 0.7, "curiosity": 0.8},
                "session": {"current_concept": "fractions", "mode": "EXPLAIN"},
            },
            access=ACCESS,
        )

    def test_capability_view_is_scoped_and_deeply_immutable(self) -> None:
        projection = self.make_projection()
        view = projection.view("pedagogy")

        self.assertEqual(view.learner["concept_states"]["fractions"]["mastery"], 0.4)
        self.assertEqual(view.learner["global"], {"confidence": 0.7})
        self.assertNotIn("curiosity", view.learner["global"])
        self.assertEqual(view.session["mode"], "EXPLAIN")
        with self.assertRaises(TypeError):
            view.session["mode"] = "TEST"  # type: ignore[index]

    def test_valid_change_is_visible_without_mutating_starting_state(self) -> None:
        starting = {
            "concept_states": {},
            "global": {},
            "session": {"mode": "EXPLAIN"},
        }
        projection = WorkingStateProjection(
            learner_id="learner-1", state=starting, access=ACCESS
        )
        projection.apply(StateChange(
            change_id="mode-1",
            owner="pedagogy",
            scope=StateScope.SESSION,
            path=("mode",),
            operation=StateOperation.SET,
            value="PRACTICE",
        ))

        self.assertEqual(projection.view("pedagogy").session["mode"], "PRACTICE")
        self.assertEqual(starting["session"]["mode"], "EXPLAIN")

    def test_rejects_unowned_and_conflicting_changes(self) -> None:
        projection = self.make_projection()
        with self.assertRaises(StateChangeRejected):
            projection.apply(StateChange(
                change_id="mastery-1",
                owner="pedagogy",
                scope=StateScope.LEARNER,
                path=("concept_states", "fractions", "mastery"),
                operation=StateOperation.SET,
                value=0.9,
            ))

        first = StateChange(
            change_id="mode-1", owner="pedagogy", scope=StateScope.SESSION,
            path=("mode",), operation=StateOperation.SET, value="PRACTICE"
        )
        projection.apply(first)
        with self.assertRaises(StateChangeConflict):
            projection.apply(StateChange(
                change_id="mode-2", owner="pedagogy", scope=StateScope.SESSION,
                path=("mode",), operation=StateOperation.SET, value="TEST"
            ))

    def test_migrates_binds_identity_and_keeps_evidence_append_only(self) -> None:
        projection = WorkingStateProjection(
            learner_id="learner-1",
            state={"concept_states": {}, "global": {}, "evidence_log": []},
            access=ACCESS,
        )
        event = {
            "script_id": "script-1", "beat_id": "beat-1", "attempt": 1,
            "event_id": "event-1", "turn_id": "turn-1", "idempotency_key": "key-1",
            "learner_id": "learner-1", "concept_id": "fractions", "item_id": "item-1",
            "outcome": "correct", "grader_confidence": 1.0, "stt_confidence": 1.0,
        }
        change = StateChange(
            change_id="evidence-1",
            owner="assessment_evidence",
            scope=StateScope.LEARNER,
            path=("evidence_ledger",),
            operation=StateOperation.APPEND,
            value=event,
            idempotency_key="key-1",
        )
        projection.apply(change)
        projection.apply(change)
        projection.apply(StateChange(
            change_id="evidence-2",
            owner="assessment_evidence",
            scope=StateScope.LEARNER,
            path=("evidence_ledger",),
            operation=StateOperation.APPEND,
            value={**event, "event_id": "event-2", "idempotency_key": "key-2"},
            idempotency_key="key-2",
        ))

        state = projection.projected_state()
        self.assertEqual(state["learner_id"], "learner-1")
        self.assertEqual(state["state_schema_version"], 2)
        self.assertEqual(
            [row["event_id"] for row in state["evidence_ledger"]], ["event-1", "event-2"]
        )
        self.assertGreater(state["concept_states"]["fractions"]["mastery"], 0.0)
        with self.assertRaises(StateChangeRejected):
            projection.apply(StateChange(
                change_id="replace-ledger",
                owner="assessment_evidence",
                scope=StateScope.LEARNER,
                path=("evidence_ledger",),
                operation=StateOperation.SET,
                value=[],
            ))
        with self.assertRaises(StateChangeRejected):
            projection.apply(StateChange(
                change_id="mismatched-key",
                owner="assessment_evidence",
                scope=StateScope.LEARNER,
                path=("evidence_ledger",),
                operation=StateOperation.APPEND,
                value={**event, "event_id": "event-3", "idempotency_key": "event-key"},
                idempotency_key="change-key",
            ))

    def test_identity_mismatch_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            WorkingStateProjection(
                learner_id="learner-2",
                state={"learner_id": "learner-1", "concept_states": {}, "global": {}},
                access=ACCESS,
            )

    def test_rejects_overlapping_ownership_and_evidence_derived_direct_writes(self) -> None:
        with self.assertRaises(StateChangeRejected):
            WorkingStateProjection(
                learner_id="learner-1",
                state={"concept_states": {}, "global": {}},
                access={
                    "first": CapabilityStateAccess(session_write=(("plan",),)),
                    "second": CapabilityStateAccess(session_write=(("plan", "mode"),)),
                },
            )

        projection = WorkingStateProjection(
            learner_id="learner-1",
            state={"concept_states": {"fractions": {"mastery": 0.4}}, "global": {}},
            access={
                "perception": CapabilityStateAccess(
                    learner_write=(("concept_states", "fractions", "mastery"),)
                )
            },
        )
        with self.assertRaises(StateChangeRejected):
            projection.apply(StateChange(
                change_id="inferred-mastery", owner="perception", scope=StateScope.LEARNER,
                path=("concept_states", "fractions", "mastery"),
                operation=StateOperation.SET, value=0.9,
            ))


if __name__ == "__main__":
    unittest.main()
