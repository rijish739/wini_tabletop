"""The dedicated safety model call (SAFETY_ROUTE_TAXONOMY.md §7).

One Gemini call, **every turn, unconditionally**. There is no precondition of any
kind and there must never be one: gating this on a lexicon trip would reinstate the
regex as gatekeeper, which is the arrangement the taxonomy inverted. If cost needs
cutting the levers are the context cache and the model id — never a precondition.

Reliability, in one place so it can be read as one thing (§7.3):

* a **5s hard wall-clock envelope**, enforced by the ``ThreadPoolExecutor`` future
  inside ``llm_vertex.generate_json`` — never an SDK-level timeout (CLAUDE.md
  gotcha: those have stalled for hours);
* **one immediate retry** on transport failure or a malformed/empty response,
  **sharing the same envelope** — it does not extend it;
* ``temperature=0``, ``response_schema`` and ``thinking_budget=0`` are mandatory,
  not defaults. A thinking-token overrun returns empty text with
  ``finish_reason=MAX_TOKENS``, which on this path would look exactly like "no
  safety concern". **Empty text is a failure, never a negative verdict** — see
  ``ModelSafetyVerdict.unavailable``, which is the only way to build a non-answer;
* memoized on ``utterance_id``, never on text, so a replayed turn does not re-bill.

**Invariant 1** (spec: source guard): nothing in this package reads the trust
decision or the transcript-doubt reading. The detector is handed a string and an
opaque id. A safety trip at any confidence always produces the safety response
path (§9), so there is nothing here for those readings to gate.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from utterance_intake.observation import SafetyClass

from . import config
from .contracts import ModelSafetyVerdict, SafetyModelStatus, SafetySessionSummary
from .prompt import PROMPT_VERSION, SCHEMA_VERSION, STATIC_BLOCK, dynamic_prompt

try:
    import debug_logger as _dbg
except ImportError:
    _dbg = None  # type: ignore[assignment]

_VALID_CLASS_NAMES = {c.value for c in SafetyClass}


class ChildSafetyDetector:
    """The safety model, behind one method.

    ``call_fn`` is the injection seam: a callable ``(prompt, static_block) -> dict``.
    Every offline test drives the detector through it, so the free lane never needs
    a credential and never makes a call.
    """

    def __init__(
        self,
        *,
        call_fn: Optional[Callable[[str, str], Any]] = None,
        memo_size: int | None = None,
    ) -> None:
        self._call_fn = call_fn
        self._memo: dict[str, ModelSafetyVerdict] = {}
        self._memo_order: list[str] = []
        self._memo_size = memo_size or config.SAFETY_MEMO_SIZE
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
        summary: SafetySessionSummary | None = None,
        deadline: float | None = None,
    ) -> ModelSafetyVerdict:
        """One verdict for one utterance. Total: it always returns a verdict object,
        and a failure is a verdict object that says it is a failure.

        ``deadline`` is a ``time.monotonic()`` instant. It is passed in rather than
        started here so the envelope is measured from **dispatch**, not from the
        moment the worker thread happened to be scheduled.
        """
        if not utterance_id:
            raise ValueError("the safety call is memoized on utterance_id")
        memoized = self._memo.get(utterance_id)
        if memoized is not None:
            return memoized

        if deadline is None:
            deadline = time.monotonic() + config.SAFETY_TIMEOUT_S
        summary = summary or SafetySessionSummary()
        prompt = dynamic_prompt(
            text=text,
            prior_safety_findings=summary.prior_safety_findings,
            prior_max_severity=summary.prior_max_severity,
            recent_context=summary.recent_context,
        )

        started = time.perf_counter()
        raw: Any = None
        attempts = 0
        failure_reason = ""
        # The retry shares the envelope; it never extends it (§7.3).
        while attempts < 2:
            remaining = deadline - time.monotonic()
            if attempts and remaining < config.SAFETY_RETRY_MIN_S:
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
            status = (
                SafetyModelStatus.TIMEOUT
                if "timeout" in (failure_reason or "").lower()
                else SafetyModelStatus.ERROR
            )
            verdict = ModelSafetyVerdict.unavailable(
                status=status,
                model_id=config.resolved_model(),
                model_pinned=config.model_pinned(),
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                attempts=attempts,
                failure_reason=failure_reason or "no response",
                latency_ms=latency_ms,
            )
        else:
            verdict = self._validate(raw, attempts=attempts, latency_ms=latency_ms)

        self._memoize(utterance_id, verdict)
        if _dbg:
            # Never the text, never the classes — a debug line is an ordinary sink.
            _dbg.emit(
                _dbg.L2, "child_safety_done",
                status=verdict.status.value, tripped=verdict.tripped,
                attempts=attempts, latency_ms=latency_ms,
            )
        return verdict

    def warm(self) -> bool:
        """Build the gateway, the schema and the cache handle OUTSIDE the envelope.

        CLAUDE.md, measured 2026-07-01: **`genai.Client(...)` construction — the
        Vertex ADC/channel setup, not the API call — is the dominant cold-start
        cost**, 4-9s for a fresh client versus sub-1.5s per call once warm. That
        number is larger than this detector's entire 5s envelope, so a first turn
        that builds the client inside `detect()` is a guaranteed `TIMEOUT` and a
        degraded first turn for whichever child happens to arrive first.

        `llm_vertex` memoizes its client **per location**, so today the safety call
        rides perception's warm client only because `VERTEX_SAFETY_LOCATION`
        happens to equal perception's. §7.2 exists precisely so that can be changed
        independently — and the moment it is, the shared warm client is gone. This
        method is what keeps that flag safe to flip.

        Call it at service start, next to the other warmers. Returns False if
        warming failed; that is not an error — the next real call retries, and a
        cold start is a latency problem, never a correctness one.
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
    def _memoize(self, utterance_id: str, verdict: ModelSafetyVerdict) -> None:
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
                location=config.VERTEX_SAFETY_LOCATION,
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
            # whole point: it is a failure, never a negative verdict.
            return None, reason
        return result.data, ""

    def _cached_content(self) -> str | None:
        """The Vertex context-cache resource holding the static block (§7.1).
        Resolved once per process; a missing/expired/stale cache never breaks a
        turn — the call falls back to the full system instruction."""
        if not self._cc_resolved:
            self._cc_resolved = True
            if config.SAFETY_CACHED_CONTENT:
                self._cc_name = config.SAFETY_CACHED_CONTENT
            else:
                try:
                    from .vertex_cache import active_name

                    self._cc_name = active_name()
                except Exception:  # noqa: BLE001 — the cache is an optimization only
                    self._cc_name = None
        return self._cc_name

    def _validate(
        self, raw: dict, *, attempts: int, latency_ms: int
    ) -> ModelSafetyVerdict:
        """The local belt behind the schema.

        Controlled generation stops *invented* class names, not *wrong* ones, and it
        cannot stop an internally inconsistent answer. Three coercions, all
        **add-only** — nothing here can clear a finding the model made:

        * out-of-catalog class names are dropped (the schema should make this
          unreachable; it is cheap insurance);
        * naming any class trips the axis, even if the model said ``axis_tripped``
          was false — a model may not clear the axis (§7.4);
        * a tripped axis with no surviving class becomes ``UNSPECIFIED_CONCERN``,
          which is exactly what that class is for (§3.7).
        """
        classes = {
            name
            for name in (raw.get("classes") or [])
            if isinstance(name, str) and name in _VALID_CLASS_NAMES
        }
        tripped = bool(raw.get("axis_tripped")) or bool(classes)
        if tripped and not classes:
            classes = {SafetyClass.UNSPECIFIED_CONCERN.value}
        if not tripped:
            return ModelSafetyVerdict(
                tripped=False, classes=frozenset(), imminence_cue=False,
                status=SafetyModelStatus.OK,
                model_id=config.resolved_model(),
                model_pinned=config.model_pinned(),
                prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
                latency_ms=latency_ms, attempts=attempts,
            )
        return ModelSafetyVerdict(
            tripped=True,
            classes=frozenset(SafetyClass(name) for name in classes),
            imminence_cue=bool(raw.get("imminence_cue")),
            named_means=bool(raw.get("named_means")),
            weapon=bool(raw.get("weapon")),
            arranged_meeting=bool(raw.get("arranged_meeting")),
            status=SafetyModelStatus.OK,
            model_id=config.resolved_model(),
            model_pinned=config.model_pinned(),
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            latency_ms=latency_ms,
            attempts=attempts,
        )
