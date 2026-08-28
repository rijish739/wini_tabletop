"""Cognitive Analyzer: utterance -> Student Cognitive Update -> state deltas.

Pipeline per turn (architecture section 6.2 / section 7 steps 2-5):

    raw text
    -> InputProcessor.normalize_input            (deterministic cleanup)
    -> ExemplarCognitiveClassifier.classify      (37 multi-label signal scores)
    -> ConceptResolver.resolve                   (concept or session inheritance)
    -> derive_cognitive_update                   (section 6.2 aggregate signals)
    -> derive_state_deltas + LearnerState write  (EMA on global fields + flags)

The label->aggregate mapping is DETERMINISTIC and lives in
derive_cognitive_update so it can be unit-tested without any model loaded.
Heavier state writes (mastery, misconception status machine, hint counters)
remain with the evidence-driven APIs in learner_state.py
(apply_probe_result / apply_bridge_result / record_hint_request) — the
analyzer only flags suspicion; it never moves mastery from text alone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# EMA weight for global-state updates: new = (1-EMA)*old + EMA*observed.
# One message is weak evidence; three consistent messages move the state most
# of the way. Matches the hint_dependency EMA convention (0.7/0.3).
EMA = 0.3

#: How long a per-concept cognitive FLAG stays "current" without being
#: re-observed (audit A-6). Flags are transient turn signals — "the student
#: asked for a hint", "a misconception may be in play" — not durable knowledge;
#: mastery and misconception_states carry the durable record separately. Two
#: weeks is long enough to survive a gap between sessions and short enough that
#: the parent dashboard stops describing last term's confusion as today's.
FLAG_TTL_DAYS = 14

# Signals whose presence (score >= FLAG_THRESHOLD) raises a per-concept flag
# for the Pedagogical Decision Engine. Flags are hints to act, not state.
FLAG_THRESHOLD = 0.5
# Misconception detection (misconception_clue) is the classifier's weakest signal
# (recall ~0.5) and sits right at 0.5 for classic overgeneralization phrasings
# ("always / never ... that's the rule"). The architecture explicitly prefers
# probing (rule 8: probe before correcting) and a served diagnostic is cheap, so
# this flag fires at a lower threshold than the others.
MISCONCEPTION_FLAG_THRESHOLD = 0.4

GLOBAL_FIELD_DEFAULTS = {"confidence": 0.5, "curiosity": 0.5, "cognitive_load": 0.5, "engagement": 0.5}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def derive_cognitive_update(scores: Dict[str, float]) -> Dict[str, float]:
    """Map the classifier's label scores to the section 6.2 aggregate signals.

    Formulas (deterministic, documented here as the single source of truth):
      confusion                : direct
      curiosity                : direct
      confidence               : 0.5 baseline, pushed up by high_confidence,
                                 down by low_confidence and (weaker) anxiety
      misconception_probability: strongest of the two misconception evidences
      transfer_attempt         : direct
      abstraction_attempt      : direct
      self_correction          : direct
      cognitive_load           : overload if stated; else a blend of
                                 confusion/frustration/anxiety pressure
      engagement               : 0.5 baseline + strongest positive engagement
                                 evidence - disengagement/frustration drag
      frustration_risk         : frustration, or anxiety at a discount
    """
    s = lambda label: float(scores.get(label, 0.0))  # noqa: E731
    return {
        "confusion": _clamp(s("confusion")),
        "curiosity": _clamp(s("curiosity")),
        "confidence": _clamp(0.5 + 0.5 * s("high_confidence") - 0.5 * s("low_confidence") - 0.2 * s("anxiety")),
        "misconception_probability": _clamp(max(s("misconception_clue"), s("recurring_error"))),
        "transfer_attempt": _clamp(s("transfer_attempt")),
        "abstraction_attempt": _clamp(s("abstraction_attempt")),
        "self_correction": _clamp(s("self_correction")),
        "cognitive_load": _clamp(max(
            s("cognitive_overload"),
            0.5 * s("confusion") + 0.3 * s("frustration") + 0.2 * s("anxiety"),
        )),
        "engagement": _clamp(
            0.5
            + 0.4 * max(s("curiosity"), s("ready_for_next"), s("transfer_attempt"))
            - 0.6 * s("disengagement")
            - 0.2 * s("frustration")
        ),
        "frustration_risk": _clamp(max(s("frustration"), 0.7 * s("anxiety"))),
    }


def derive_state_deltas(
    update: Dict[str, float],
    signals: List[str],
    resolution: Dict[str, Any],
) -> Dict[str, Any]:
    """Deterministic state-delta plan from one analyzed turn.

    global: EMA targets for the four persisted global fields.
    concept_flags: action hints attached to the resolved concept (only when
    resolution did not abstain into nothing).
    """
    flags = []
    if update["misconception_probability"] >= MISCONCEPTION_FLAG_THRESHOLD:
        flags.append("misconception_suspected")
    if update["transfer_attempt"] >= FLAG_THRESHOLD:
        flags.append("transfer_ready_evidence")
    if "request_hint" in signals:
        flags.append("hint_requested")
    if "prerequisite_weakness" in signals:
        flags.append("prerequisite_weakness_clue")
    if update["frustration_risk"] >= 0.6:
        flags.append("frustration_risk")
    if update["self_correction"] >= FLAG_THRESHOLD:
        flags.append("self_corrected")

    signal_set = set(signals or [])
    # Missing signals are not counter-evidence. Persist only observed fields so
    # neutral defaults do not wash out a learner estimate on ordinary answer turns.
    observed_global = {}
    if signal_set & {"high_confidence", "low_confidence", "anxiety"}:
        observed_global["confidence"] = update["confidence"]
    if "curiosity" in signal_set:
        observed_global["curiosity"] = update["curiosity"]
    if signal_set & {"cognitive_overload", "confusion", "frustration", "anxiety"}:
        observed_global["cognitive_load"] = update["cognitive_load"]
    if signal_set & {"curiosity", "ready_for_next", "transfer_attempt",
                     "disengagement", "frustration"}:
        observed_global["engagement"] = update["engagement"]

    return {
        "global": observed_global,
        "concept_id": resolution.get("concept_id"),
        "concept_flags": flags if resolution.get("concept_id") else [],
        # Carried so apply_deltas can persist `last_signals` on the concept state,
        # which §6.2 has always documented and nothing ever wrote (audit D-8).
        "signals": list(signals or []),
    }


def apply_deltas(state, deltas: Dict[str, Any], ema: float = EMA) -> Dict[str, float]:
    """Write the deltas into a learner_state.LearnerState (EMA on globals,
    flags + last_signals on the concept state). Returns the new global values.

    Flags are TIME-STAMPED and DECAY (audit A-6). They used to accumulate and
    never clear, which made a transient one-turn signal permanent: the live
    device carried `misconception_suspected` on 4 concepts, `hint_requested` on
    6 and `transfer_ready_evidence` on 5, with no timestamps and no way to tell
    a current condition from one moment months ago. The tutor is unaffected
    either way — it reads the TURN-LOCAL flags, not these — but the parent
    dashboard presents them as the child's present state, and sorts topics by
    how many there are.
    """
    g = state.data.setdefault("global", {})
    observations = state.data.setdefault("global_observations", {})
    new_values = {}
    for field, observed in deltas["global"].items():
        old = float(g.get(field, GLOBAL_FIELD_DEFAULTS[field]))
        g[field] = round((1.0 - ema) * old + ema * float(observed), 4)
        observations[field] = int(observations.get(field, 0)) + 1
        new_values[field] = g[field]
    cid = deltas.get("concept_id")
    if cid:
        cs = state.concept_states.setdefault(cid, {})
        now = datetime.now(timezone.utc)
        seen = cs.setdefault("flag_seen", {})
        existing = cs.setdefault("flags", [])
        for flag in deltas["concept_flags"]:
            if flag not in existing:
                existing.append(flag)
            seen[flag] = now.isoformat()          # refresh on every re-observation
        # Undated flags predate this change; date them from the concept's last
        # practice rather than from now, so an old signal starts its decay from
        # when it was plausibly set instead of being silently renewed today.
        for flag in existing:
            seen.setdefault(flag, cs.get("last_practiced") or now.isoformat())
        # prune anything not re-observed within the TTL
        live = []
        for flag in existing:
            try:
                ts = datetime.fromisoformat(seen[flag])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                ts = now
            if (now - ts) <= timedelta(days=FLAG_TTL_DAYS):
                live.append(flag)
            else:
                seen.pop(flag, None)
        cs["flags"] = live
        # §6.2 documented this field and nothing ever wrote it (audit D-8).
        if deltas.get("signals") is not None:
            cs["last_signals"] = list(deltas["signals"])
    return new_values


class CognitiveAnalyzer:
    """Assembled analyzer. Heavy models load lazily on first use; stubs may be
    injected for tests (anything with .classify(text) / .resolve(text, ctx))."""

    def __init__(self, classifier=None, resolver=None, processor=None) -> None:
        self._classifier = classifier
        self._resolver = resolver
        if processor is None:
            from cognitive_input_processor.input_processor import InputProcessor
            processor = InputProcessor()
        self.processor = processor

    @property
    def classifier(self):
        if self._classifier is None:
            from cognitive_classifier import ExemplarCognitiveClassifier
            self._classifier = ExemplarCognitiveClassifier.load()
        return self._classifier

    @property
    def resolver(self):
        if self._resolver is None:
            from concept_resolver import ConceptResolver
            self._resolver = ConceptResolver.load()
        return self._resolver

    def analyze(self, text: str, current_concept: Optional[str] = None) -> Dict[str, Any]:
        """One turn: returns the Student Cognitive Update (section 6.2)."""
        normalized = self.processor.normalize_input(text)
        clf = self.classifier.classify(normalized, top_evidence=0)
        resolution = self.resolver.resolve(normalized, current_concept=current_concept)
        update = derive_cognitive_update(clf["scores"])
        deltas = derive_state_deltas(update, clf["signals"], resolution)
        # §6.1's deterministic "the student brought their own instance" cue.
        # Migrated to normalized text (ticket 03): detect_problem is the ONE
        # implementation; the analyzer calls it on the NFKC-normalized text it
        # already holds.  The intake's observe() calls the same function on its
        # NFC-normalized text.  analysis["problem_cue"] is deleted — consumers
        # read analysis["problem"] (a ProblemReading) instead.
        from utterance_intake.intake import detect_problem
        problem = detect_problem(normalized)
        return {
            "raw_text": text,
            "normalized_text": normalized,
            "problem": problem,
            "signals": clf["signals"],
            "signal_scores": {k: v for k, v in clf["scores"].items() if v >= 0.05},
            "concept": resolution,
            "cognitive_update": update,
            "state_deltas": deltas,
        }

    def analyze_and_apply(self, text: str, state, current_concept: Optional[str] = None) -> Dict[str, Any]:
        """analyze() + write the deltas into the learner state (not saved —
        caller decides when to persist, typically once per turn)."""
        result = self.analyze(text, current_concept=current_concept)
        result["new_global_state"] = apply_deltas(state, result["state_deltas"])
        return result


def _main() -> None:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="Analyze one student utterance.")
    parser.add_argument("text")
    parser.add_argument("--current-concept", default=None)
    args = parser.parse_args()
    result = CognitiveAnalyzer().analyze(args.text, current_concept=args.current_concept)
    print(_json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
