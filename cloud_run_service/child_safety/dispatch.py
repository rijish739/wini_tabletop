"""Dispatching the safety call in parallel with perception, and the hold.

The turn topology this implements (SAFETY_ROUTE_TAXONOMY.md §7.1, spec invariant 6):

    safety dispatched FIRST
    perception dispatched immediately after
    perception's output HELD until the safety verdict is analyzed
    ...bounded by the 5s envelope, then released degraded with the
       `safety_model_unavailable` stamp

Safety goes first because its prompt is small — no ~6k cached concept block, no
MiniLM candidate hints — so its verdict is *expected* to arrive before perception's
and the hold is expected to cost nothing. The bound exists for the day that
expectation is wrong, and it is measured from **dispatch**, not from the moment the
worker thread was scheduled, so a busy pool cannot silently extend the envelope.

The call is **not abandoned at the deadline** (§7.3). A verdict arriving late still
unions into the case record and can still escalate (§6.4) — that is what
``late_verdict()`` is for. Safety findings may arrive asynchronously; the case store
must support updating an open record.

**NOT YET COLLECTED (slice 12).** ``late_verdict()`` and its consumer
``interaction_control.union_late`` are implemented and tested, but **no runtime
caller collects a late verdict today**. Collecting one requires a case store that
can update an already-written record, and the current sink is a session dict plus a
``notify_safety`` callback — neither can be revised after the turn is released. So
the mechanism is ready and the plumbing is absent; the gap is in the store, not
here. Do not describe the system as escalating on late verdicts until a store with
update semantics exists and calls this.
"""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeoutError

from . import config
from .contracts import ModelSafetyVerdict, SafetyModelStatus, SafetySessionSummary
from .detector import ChildSafetyDetector
from .prompt import PROMPT_VERSION, SCHEMA_VERSION

#: One shared pool. Safety is one small call per turn; a per-turn pool would make
#: thread construction part of the envelope it is supposed to bound.
#:
#: Note the pool underneath: ``llm_vertex`` submits into its OWN executor, shared
#: with perception and generation. Queue time there is charged to this envelope, so
#: under load the 5s bound is reached sooner rather than exceeded — the failure mode
#: is a `TIMEOUT` verdict and a degraded turn, which is a non-answer and never a
#: negative one. That is survivable by construction; it is not free, and if degraded
#: turns start showing up in the divergence metric under load, this nesting is the
#: first place to look.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="child-safety")


class SafetyDispatch:
    """One in-flight safety call: dispatched before perception, awaited after."""

    def __init__(self, future: Future, *, deadline: float) -> None:
        self._future = future
        self._deadline = deadline
        self._verdict: ModelSafetyVerdict | None = None

    @property
    def deadline(self) -> float:
        return self._deadline

    def await_verdict(self) -> ModelSafetyVerdict:
        """Block until the verdict lands or the envelope expires, whichever is first.

        This is the hold. On expiry it returns a ``TIMEOUT`` verdict — a non-answer,
        not a negative one — and the turn proceeds in degraded mode with the
        ``safety_model_unavailable`` stamp. The future is deliberately **not**
        cancelled: see ``late_verdict``.
        """
        if self._verdict is not None:
            return self._verdict
        remaining = max(0.0, self._deadline - time.monotonic())
        try:
            self._verdict = self._future.result(timeout=remaining)
        except _FutureTimeoutError:
            self._verdict = ModelSafetyVerdict.unavailable(
                status=SafetyModelStatus.TIMEOUT,
                model_id=config.resolved_model(),
                model_pinned=config.model_pinned(),
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                failure_reason=f"envelope of {config.SAFETY_TIMEOUT_S}s expired",
            )
        except Exception as exc:  # noqa: BLE001 — a detector crash is a non-answer
            self._verdict = ModelSafetyVerdict.unavailable(
                status=SafetyModelStatus.ERROR,
                model_id=config.resolved_model(),
                model_pinned=config.model_pinned(),
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                failure_reason=f"{type(exc).__name__}: {exc}",
            )
        return self._verdict

    def late_verdict(self) -> ModelSafetyVerdict | None:
        """A verdict that arrived after the envelope, or None if still outstanding.

        Non-blocking. Stamped ``LATE`` so the case record shows it unioned in after
        the turn was released; it may add classes and raise severity, and it may
        never clear or downgrade (§6.4).
        """
        if not self._future.done():
            return None
        try:
            landed = self._future.result(timeout=0)
        except Exception:  # noqa: BLE001
            return None
        if self._verdict is not None and self._verdict.available:
            return None                      # already counted at await time
        if not landed.available:
            return None
        return ModelSafetyVerdict(
            tripped=landed.tripped,
            classes=landed.classes,
            imminence_cue=landed.imminence_cue,
            named_means=landed.named_means,
            weapon=landed.weapon,
            arranged_meeting=landed.arranged_meeting,
            status=SafetyModelStatus.LATE,
            model_id=landed.model_id,
            model_pinned=landed.model_pinned,
            prompt_version=landed.prompt_version,
            schema_version=landed.schema_version,
            latency_ms=landed.latency_ms,
            attempts=landed.attempts,
        )


class ChildSafetyGateway:
    """The seam the Turn Coordinator holds. One detector, one dispatch per turn."""

    def __init__(self, detector: ChildSafetyDetector | None = None) -> None:
        self._detector = detector or ChildSafetyDetector()

    @property
    def detector(self) -> ChildSafetyDetector:
        return self._detector

    def dispatch(
        self,
        *,
        utterance_id: str,
        text: str,
        summary: SafetySessionSummary | None = None,
    ) -> SafetyDispatch:
        """Start the call. Returns immediately; the envelope starts *now*."""
        deadline = time.monotonic() + config.SAFETY_TIMEOUT_S
        future = _EXECUTOR.submit(
            self._detector.detect,
            utterance_id=utterance_id,
            text=text,
            summary=summary,
            deadline=deadline,
        )
        return SafetyDispatch(future, deadline=deadline)
