"""The dedicated personal-data model call (PERSONAL_DATA_CONTRACT.md §2, §13).

One Gemini call, every turn, fired **immediately after Utterance Intake**. The
ordering is forced rather than preferred: redaction is exact-match against
``normalized_text`` (§4), and Intake is what produces ``normalized_text``. Intake is
pure, deterministic and sub-millisecond, so this costs nothing.

**Model-only. There is no lexicon, no regex, no shape rule and no outage net** — not
as an omission but as a measured decision (§2). A generic pattern detector scores
F1 = 0.379 on maths-tutoring dialogue and fails precisely by *eating the maths*:
"numeric expressions frequently resemble structured identifiers", and false redactions
"cluster in math-dense text regions" (ticket 08 §3.3, MathEd-PII). A maths tutor that
redacts ``3825`` has broken the lesson, which is the one §11 outcome that is
unrecoverable.

The consequence, stated plainly rather than hidden: **nothing here can protect a sink
in-turn.** A Vertex outage means zero detection. What makes that survivable is not
anything in this file — it is ``redaction.redact`` returning ``None`` and the sinks
refusing to write a transcript without one (§8).

Reliability, in one place so it can be read as one thing:

* a **5s hard wall-clock envelope**, enforced by the ``ThreadPoolExecutor`` future
  inside ``llm_vertex.generate_json`` — never an SDK-level timeout (CLAUDE.md gotcha:
  those have stalled for hours);
* **one immediate retry** on transport failure or a malformed/empty response,
  **sharing the same envelope** — it does not extend it;
* ``temperature=0``, ``response_schema`` and ``thinking_budget=0`` are mandatory, not
  defaults. A thinking-token overrun returns empty text with
  ``finish_reason=MAX_TOKENS``, which on this path would look exactly like "no
  personal data". **Empty text is a failure, never an empty finding list** — see
  ``PersonalDataVerdict.unavailable``, the only way to build a non-answer;
* memoized on ``utterance_id``, never on text, so a replayed turn does not re-bill and
  two children saying the same words cannot share a verdict.

**This module logs nothing about what it found.** The debug line at the end carries a
count and a status and no classes, because a debug line is an ordinary sink and §9
gives class labels to the turn's analytics row, not to the SSE stream.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from . import config
from .contracts import (
    IdentifierClass,
    IdentifierFinding,
    PersonalDataContext,
    PersonalDataVerdict,
    VerdictStatus,
)
from .prompt import PROMPT_VERSION, SCHEMA_VERSION, STATIC_BLOCK, dynamic_prompt

try:
    import debug_logger as _dbg
except ImportError:
    _dbg = None  # type: ignore[assignment]

_VALID_CLASS_NAMES = {c.value for c in IdentifierClass}


class PersonalDataDetector:
    """The personal-data model, behind one method.

    ``call_fn`` is the injection seam: a callable ``(prompt, static_block) -> dict``.
    Every offline test drives the detector through it, so the free lane never needs a
    credential and never makes a call.
    """

    def __init__(
        self,
        *,
        call_fn: Optional[Callable[[str, str], Any]] = None,
        memo_size: int | None = None,
    ) -> None:
        self._call_fn = call_fn
        self._memo: dict[str, PersonalDataVerdict] = {}
        self._memo_order: list[str] = []
        self._memo_size = memo_size or config.PERSONAL_DATA_MEMO_SIZE
        self._gateway = None
        self._schema = None
        self._cc_name: str | None = None
        self._cc_resolved = False

    # ------------------------------------------------------------------ public
    def detect(
        self,
        *,
        utterance_id: str,
        text: str,
        context: PersonalDataContext | None = None,
        deadline: float | None = None,
    ) -> PersonalDataVerdict:
        """One verdict for one utterance. Total: it always returns a verdict object,
        and a failure is a verdict object that says it is a failure.

        ``deadline`` is a ``time.monotonic()`` instant. It is passed in rather than
        started here so the envelope is measured from **dispatch**, not from the
        moment the worker thread happened to be scheduled.
        """
        if not utterance_id:
            raise ValueError("the personal-data call is memoized on utterance_id")
        memoized = self._memo.get(utterance_id)
        if memoized is not None:
            return memoized

        if deadline is None:
            deadline = time.monotonic() + config.PERSONAL_DATA_TIMEOUT_S
        context = context or PersonalDataContext()
        prompt = dynamic_prompt(text=text, recent_context=context.recent_context)

        started = time.perf_counter()
        raw: Any = None
        attempts = 0
        failure_reason = ""
        # The retry shares the envelope; it never extends it.
        while attempts < 2:
            remaining = deadline - time.monotonic()
            if attempts and remaining < config.PERSONAL_DATA_RETRY_MIN_S:
                # Not enough envelope left for a round-trip. Starting one here would
                # produce a call we abandon and still pay for.
                failure_reason = failure_reason or "envelope exhausted before retry"
                break
            if remaining <= 0:
                failure_reason = failure_reason or "envelope exhausted"
                break
            attempts += 1
            raw, failure_reason = self._attempt(prompt, remaining)
            if raw is not None:
                break

        latency_ms = int((time.perf_counter() - started) * 1000)
        if raw is None:
            verdict = PersonalDataVerdict.unavailable(
                utterance_id=utterance_id,
                model_id=config.resolved_model(),
                model_pinned=config.model_pinned(),
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                attempts=attempts,
                failure_reason=failure_reason or "no response",
                latency_ms=latency_ms,
            )
        else:
            verdict = self._validate(
                raw,
                utterance_id=utterance_id,
                attempts=attempts,
                latency_ms=latency_ms,
            )

        self._memoize(utterance_id, verdict)
        if _dbg:
            # A count and a status. Never the text, never the values, and never the
            # classes — a debug line is an ordinary sink and §9 gives class labels to
            # the analytics row alone.
            _dbg.emit(
                _dbg.L2, "personal_data_done",
                status=verdict.status.value, n_findings=len(verdict.findings),
                attempts=attempts, latency_ms=latency_ms,
            )
        return verdict

    def warm(self) -> bool:
        """Build the gateway, the schema and the cache handle OUTSIDE the envelope.

        CLAUDE.md, measured 2026-07-01: ``genai.Client(...)`` construction — the Vertex
        ADC/channel setup, not the API call — is the dominant cold-start cost, 4-9s for
        a fresh client versus sub-1.5s per call once warm. That number is larger than
        this detector's entire 5s envelope, so a first turn that builds the client
        inside ``detect()`` is a guaranteed non-answer — and on this path a non-answer
        means the first child's turn is logged with no transcript at all.

        ``llm_vertex`` memoizes its client **per location**, so today this call rides
        perception's warm client only because ``VERTEX_PERSONAL_DATA_LOCATION`` happens
        to equal perception's. §13 exists precisely so that can be changed
        independently; this method is what keeps that flag safe to flip.

        Returns False if warming failed; that is not an error — the next real call
        retries, and a cold start is a latency problem, never a correctness one.
        """
        try:
            if self._gateway is None:
                from runtime.model_gateway import VertexModelGateway

                self._gateway = VertexModelGateway()
            if self._schema is None:
                from .schema import build_schema

                self._schema = build_schema()
            self._cached_content()
            return True
        except Exception:  # noqa: BLE001 — warming is an optimization, never a gate
            return False

    # ----------------------------------------------------------------- private
    def _memoize(self, utterance_id: str, verdict: PersonalDataVerdict) -> None:
        self._memo[utterance_id] = verdict
        self._memo_order.append(utterance_id)
        if len(self._memo_order) > self._memo_size:
            self._memo.pop(self._memo_order.pop(0), None)

    def _attempt(self, prompt: str, remaining: float) -> tuple[Any, str]:
        """One round-trip. Returns ``(payload, failure_reason)``; payload is None on
        any failure, including an empty response."""
        if self._call_fn is not None:
            try:
                payload = self._call_fn(prompt, STATIC_BLOCK)
            except Exception as exc:  # noqa: BLE001 — injected stub failures
                return None, f"{type(exc).__name__}: {exc}"
            if not isinstance(payload, dict):
                return None, "empty or malformed response"
            return payload, ""

        if self._gateway is None:
            from runtime.model_gateway import VertexModelGateway

            self._gateway = VertexModelGateway()
        if self._schema is None:
            from .schema import build_schema

            self._schema = build_schema()

        cached = self._cached_content()
        try:
            result = self._gateway.generate_json(
                prompt,
                response_schema=self._schema,
                system=(None if cached else STATIC_BLOCK),
                cached_content=cached,
                model=config.resolved_model(),
                location=config.VERTEX_PERSONAL_DATA_LOCATION,
                timeout_s=remaining,
                temperature=0.0,
            )
        except TimeoutError as exc:
            return None, f"timeout: {exc}"
        except Exception as exc:  # noqa: BLE001 — transport
            if cached:
                self._cc_name = None      # dead cache -> full prompt from now on
            return None, f"{type(exc).__name__}: {exc}"
        if result is None or not getattr(result, "ok", False):
            reason = getattr(result, "reason", "") or "empty or malformed response"
            if cached:
                self._cc_name = None
            # An empty reply with finish_reason=MAX_TOKENS lands here, which is the
            # whole point: it is a failure, never an empty finding list.
            return None, reason
        return result.data, ""

    def _cached_content(self) -> str | None:
        """The Vertex context-cache resource holding the static block (§13). Resolved
        once per process; a missing/expired/stale cache never breaks a turn — the call
        falls back to the full system instruction."""
        if not self._cc_resolved:
            self._cc_resolved = True
            if config.PERSONAL_DATA_CACHED_CONTENT:
                self._cc_name = config.PERSONAL_DATA_CACHED_CONTENT
            else:
                try:
                    from .vertex_cache import active_name

                    self._cc_name = active_name()
                except Exception:  # noqa: BLE001 — the cache is an optimization only
                    self._cc_name = None
        return self._cc_name

    def _validate(
        self,
        raw: dict,
        *,
        utterance_id: str,
        attempts: int,
        latency_ms: int,
    ) -> PersonalDataVerdict:
        """The local belt behind the schema.

        Controlled generation stops *invented* class names, not *wrong* ones. Three
        coercions, all of them about a finding that is not a finding at all:

        * a finding with a non-string or empty ``value`` is dropped — there is nothing
          to remove;
        * an out-of-catalog class name is dropped (the schema should make this
          unreachable; it is cheap insurance);
        * exact duplicates collapse (the ``frozenset`` does this) — two findings of the
          same class and value are one identifier named twice.

        **A value that is not a substring of the utterance is NOT dropped here**, and
        that is deliberate. It would be the kinder behaviour — keep the honest findings,
        keep the transcript — and §4 rules it out: a named substring that cannot be
        found means *redaction has failed and cannot be verified*, so the turn is
        stamped ``redaction_incomplete`` and the sink receives no transcript at all. A
        detector that quietly discarded the unmatchable finding would convert an
        unverifiable redaction into an apparently clean one, which is the single thing
        §4 is written to prevent. The check therefore lives in ``redaction.redact``,
        where its consequence is fail-closed rather than fail-quiet.

        Note what is also NOT here: no threshold, no shape rule, no length rule, no
        digit-run heuristic. §5 is explicit that this contract has no tie-break, because
        adding one is how the maths gets eaten.
        """
        findings = set()
        for row in raw.get("findings") or []:
            if not isinstance(row, dict):
                continue
            name = row.get("identifier_class")
            value = row.get("value")
            if not isinstance(name, str) or name not in _VALID_CLASS_NAMES:
                continue
            if not isinstance(value, str) or not value:
                continue
            findings.add(
                IdentifierFinding(identifier_class=IdentifierClass(name), value=value)
            )
        return PersonalDataVerdict(
            utterance_id=utterance_id,
            status=VerdictStatus.LANDED,
            findings=frozenset(findings),
            model_id=config.resolved_model(),
            model_pinned=config.model_pinned(),
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            latency_ms=latency_ms,
            attempts=attempts,
        )
