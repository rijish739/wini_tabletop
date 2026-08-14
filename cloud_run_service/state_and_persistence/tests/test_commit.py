from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from learner_state import LearnerState
from runtime.contracts import StateChange, StateOperation, StateScope
from state_and_persistence import (
    CapabilityStateAccess,
    DeterministicPersistenceAdapter,
    LearnerStatePersistenceAdapter,
    StateAndPersistence,
    StateCommitFailed,
    StaleState,
)


ACCESS = {
    "pedagogy": CapabilityStateAccess(
        session_read=(("mode",),), session_write=(("mode",),)
    )
}


def mode_change(value: str = "PRACTICE") -> StateChange:
    return StateChange(
        change_id=f"mode-{value.lower()}",
        owner="pedagogy",
        scope=StateScope.SESSION,
        path=("mode",),
        operation=StateOperation.SET,
        value=value,
    )


class TurnCommitTests(unittest.TestCase):
    def test_deterministic_adapter_commits_all_changes_once(self) -> None:
        adapter = DeterministicPersistenceAdapter({
            "learner_id": "learner-1", "concept_states": {}, "global": {},
            "session": {"mode": "EXPLAIN"},
        })
        state = StateAndPersistence(adapter=adapter, access=ACCESS)
        projection = state.begin(learner_id="learner-1")
        projection.apply(mode_change())

        commit = state.commit(turn_id="turn-1", projection=projection)

        self.assertEqual(commit.turn_id, "turn-1")
        self.assertEqual(commit.applied_change_ids, ("mode-practice",))
        self.assertEqual(adapter.committed_state["session"]["mode"], "PRACTICE")
        self.assertEqual(adapter.commit_count, 1)
        with self.assertRaises(StateCommitFailed):
            state.commit(turn_id="turn-1", projection=projection)

    def test_failed_commit_leaves_durable_state_unchanged_and_can_retry(self) -> None:
        original = {
            "learner_id": "learner-1", "concept_states": {}, "global": {},
            "session": {"mode": "EXPLAIN"},
        }
        adapter = DeterministicPersistenceAdapter(original)
        state = StateAndPersistence(adapter=adapter, access=ACCESS)
        projection = state.begin(learner_id="learner-1")
        projection.apply(mode_change())
        adapter.fail_next_commit("store unavailable")

        with self.assertRaisesRegex(StateCommitFailed, "store unavailable"):
            state.commit(turn_id="turn-1", projection=projection)
        self.assertEqual(adapter.committed_state, original)

        commit = state.commit(turn_id="turn-1", projection=projection)
        self.assertEqual(commit.applied_change_ids, ("mode-practice",))

    def test_stale_projection_cannot_overwrite_a_newer_commit(self) -> None:
        adapter = DeterministicPersistenceAdapter({
            "learner_id": "learner-1", "concept_states": {}, "global": {},
            "session": {"mode": "EXPLAIN"},
        })
        state = StateAndPersistence(adapter=adapter, access=ACCESS)
        first = state.begin(learner_id="learner-1")
        stale = state.begin(learner_id="learner-1")
        first.apply(mode_change("PRACTICE"))
        stale.apply(mode_change("TEST"))
        state.commit(turn_id="turn-1", projection=first)

        with self.assertRaises(StaleState):
            state.commit(turn_id="turn-2", projection=stale)

    def test_projection_cannot_commit_through_another_interface(self) -> None:
        original = {
            "learner_id": "learner-1", "concept_states": {}, "global": {},
            "session": {"mode": "EXPLAIN"},
        }
        adapter_a = DeterministicPersistenceAdapter(original)
        adapter_b = DeterministicPersistenceAdapter(original)
        state_a = StateAndPersistence(adapter=adapter_a, access=ACCESS)
        state_b = StateAndPersistence(adapter=adapter_b, access=ACCESS)
        projection = state_a.begin(learner_id="learner-1")
        projection.apply(mode_change())

        with self.assertRaises(StateCommitFailed):
            state_b.commit(turn_id="turn-1", projection=projection)
        self.assertEqual(adapter_a.commit_count, 0)
        self.assertEqual(adapter_b.commit_count, 0)

    def test_production_adapter_reuses_atomic_learner_state_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "learner.json"
            learner_state = LearnerState(path=path, data={
                "learner_id": "learner-1", "concept_states": {}, "global": {},
                "session": {"mode": "EXPLAIN"},
            })
            state = StateAndPersistence(
                adapter=LearnerStatePersistenceAdapter(learner_state), access=ACCESS
            )
            projection = state.begin(learner_id="learner-1")
            projection.apply(mode_change())

            state.commit(turn_id="turn-1", projection=projection)

            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["session"]["mode"], "PRACTICE")
            self.assertEqual(learner_state.data, persisted)

    def test_production_durable_store_is_one_write_and_failure_does_not_publish(self) -> None:
        class DurableStore:
            def __init__(self) -> None:
                self.saved: list[dict] = []
                self.failure: str | None = "firestore unavailable"

            def save(self, value: dict) -> None:
                if self.failure:
                    raise RuntimeError(self.failure)
                self.saved.append(value)

        original = {
            "learner_id": "learner-1", "concept_states": {}, "global": {},
            "session": {"mode": "EXPLAIN"},
        }
        learner_state = LearnerState(path=None, data=original.copy())
        store = DurableStore()
        state = StateAndPersistence(
            adapter=LearnerStatePersistenceAdapter(learner_state, store), access=ACCESS
        )
        projection = state.begin(learner_id="learner-1")
        projection.apply(mode_change())

        with self.assertRaisesRegex(StateCommitFailed, "firestore unavailable"):
            state.commit(turn_id="turn-1", projection=projection)
        self.assertEqual(learner_state.data["session"]["mode"], "EXPLAIN")
        self.assertEqual(store.saved, [])

        store.failure = None
        state.commit(turn_id="turn-1", projection=projection)
        self.assertEqual(len(store.saved), 1)
        self.assertEqual(learner_state.data["session"]["mode"], "PRACTICE")

    def test_invalid_turn_identity_is_rejected_before_persistence(self) -> None:
        adapter = DeterministicPersistenceAdapter({
            "learner_id": "learner-1", "concept_states": {}, "global": {},
            "session": {"mode": "EXPLAIN"},
        })
        state = StateAndPersistence(adapter=adapter, access=ACCESS)
        projection = state.begin(learner_id="learner-1")
        projection.apply(mode_change())

        with self.assertRaises(StateCommitFailed):
            state.commit(turn_id="", projection=projection)
        self.assertEqual(adapter.commit_count, 0)
        self.assertEqual(adapter.committed_state["session"]["mode"], "EXPLAIN")

    def test_append_idempotency_survives_commit_and_reload(self) -> None:
        access = {
            "interaction_control": CapabilityStateAccess(
                session_read=(("context",),), session_write=(("context",),)
            )
        }
        adapter = DeterministicPersistenceAdapter({
            "learner_id": "learner-1", "concept_states": {}, "global": {},
            "session": {"context": []},
        })
        state = StateAndPersistence(adapter=adapter, access=access)
        change = StateChange(
            change_id="context-1", owner="interaction_control", scope=StateScope.SESSION,
            path=("context",), operation=StateOperation.APPEND,
            value={"role": "learner", "text": "hello"}, idempotency_key="turn-1:context",
        )
        first = state.begin(learner_id="learner-1")
        first.apply(change)
        state.commit(turn_id="turn-1", projection=first)
        replay = state.begin(learner_id="learner-1")

        self.assertFalse(replay.apply(change))
        self.assertEqual(replay.view("interaction_control").session["context"], (
            {"role": "learner", "text": "hello"},
        ))


if __name__ == "__main__":
    unittest.main()
