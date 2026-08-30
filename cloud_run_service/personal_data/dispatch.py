"""Dispatching the personal-data call, and §7's two deadlines.

The turn topology this implements:

    Utterance Intake produces normalized_text
    personal-data call dispatched IMMEDIATELY after it
    ...perception, retrieval, planning all run...
    persisting sinks wait the full 5s envelope        -> fail CLOSED  (§8)
    generation takes whatever has landed by then      -> fail OPEN    (§8)

**Two deadlines, one call** (§7):

| deadline | bound | missed => |
|---|---|---|
| generation | opportunistic: waits only until it is otherwise ready to build its prompt, adding no wall-clock of its own | fail open |
| persisting sinks | the full 5s envelope | fail closed |

Firing right after Intake buys the whole perception -> retrieval span as headroom, so
the verdict usually lands before generation needs it **without adding a millisecond**.
That is the entire latency argument, and it does not depend on the model being fast.

``landed_verdict()`` is the opportunistic read: non-blocking, returns ``None`` if the
call is still in flight. ``await_verdict()`` is the persisting-sink read: it blocks up
to the remaining envelope.

**No retro-scrub, ever** (§8). There is no ``late_verdict()`` here and there must not
be one — compare ``child_safety.dispatch``, where a late verdict legitimately unions
into an open safeguarding case. You cannot recall an SSE frame or a shipped log line,
so a verdict that arrives after the sinks have written changes nothing; offering an API
for it would imply a promise the product cannot keep. The one late-verdict consumer the
contract does name is §9.2's safety case record, and that path unions class labels into
a record the *safety* side owns, not into anything here.
"""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeoutError

from . import config
from .contracts import PersonalDataContext, PersonalDataVerdict
from .detector import PersonalDataDetector
from .prompt import PROMPT_VERSION, SCHEMA_VERSION

#: One shared pool. Personal data is one small call per turn; a per-turn pool would
#: make thread construction part of the envelope it is supposed to bound.
#:
#: Note the pool underneath: ``llm_vertex`` submits into its OWN executor, shared with
#: perception, generation and child_safety. Queue time there is charged to this
#: envelope, so under load the 5s bound is reached sooner rather than exceeded — the
#: failure mode is an ``UNAVAILABLE`` verdict and a transcript-free log line, never a
#: false "nothing was disclosed". That is survivable by construction; it is not free.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="personal-data")


class PersonalDataDispatch:
    """One in-flight personal-data call and the two ways to read it."""

    def __init__(self, future: Future, *, deadline: float, utterance_id: str) -> None:
        self._future = future
        self._deadline = deadline
        self._utterance_id = utterance_id
        self._verdict: PersonalDataVerdict | None = None

    @property
    def deadline(self) -> float:
        return self._deadline

    def landed_verdict(self) -> PersonalDataVerdict | None:
        """The **opportunistic** read (§7, generation deadline). Non-blocking.

        ``None`` means "not yet", and the caller must treat that as §8's fail-open: it
        proceeds on unredacted text with the anti-echo prompt instruction. It must not
        be read as "no personal data" — that is what ``VerdictStatus`` is for, and this
        method returning ``None`` is not a verdict at all.
        """
        if self._verdict is not None:
            return self._verdict
        if not self._future.done():
            return None
        return self.await_verdict()

    def await_verdict(self) -> PersonalDataVerdict:
        """The **persisting-sink** read (§7). Blocks up to the remaining envelope.

        Total: on expiry it returns an ``UNAVAILABLE`` verdict, which is a non-answer
        rather than an empty finding list. The future is deliberately not cancelled —
        an in-flight call that lands a moment later costs nothing and, unlike the
        safety path, has no consumer to escalate to; letting it complete simply keeps
        the memo warm for a replay of the same ``utterance_id``.
        """
        if self._verdict is not None:
            return self._verdict
        remaining = max(0.0, self._deadline - time.monotonic())
        try:
            self._verdict = self._future.result(timeout=remaining)
        except _FutureTimeoutError:
            self._verdict = PersonalDataVerdict.unavailable(
                utterance_id=self._utterance_id,
                model_id=config.resolved_model(),
                model_pinned=config.model_pinned(),
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                failure_reason=(
                    f"envelope of {config.PERSONAL_DATA_TIMEOUT_S}s expired"
                ),
            )
        except Exception as exc:  # noqa: BLE001 — a detector crash is a non-answer
            self._verdict = PersonalDataVerdict.unavailable(
                utterance_id=self._utterance_id,
                model_id=config.resolved_model(),
                model_pinned=config.model_pinned(),
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                failure_reason=f"{type(exc).__name__}: {exc}",
            )
        return self._verdict


class PersonalDataGateway:
    """The seam the Turn Coordinator holds. One detector, one dispatch per turn."""

    def __init__(self, detector: PersonalDataDetector | None = None) -> None:
        self._detector = detector or PersonalDataDetector()

    @property
    def detector(self) -> PersonalDataDetector:
        return self._detector

    def dispatch(
        self,
        *,
        utterance_id: str,
        text: str,
        context: PersonalDataContext | None = None,
    ) -> PersonalDataDispatch:
        """Start the call. Returns immediately; the envelope starts *now*."""
        deadline = time.monotonic() + config.PERSONAL_DATA_TIMEOUT_S
        future = _EXECUTOR.submit(
            self._detector.detect,
            utterance_id=utterance_id,
            text=text,
            context=context,
            deadline=deadline,
        )
        return PersonalDataDispatch(
            future, deadline=deadline, utterance_id=utterance_id
        )
