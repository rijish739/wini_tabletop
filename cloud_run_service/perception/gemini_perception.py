"""GeminiPerception — one structured Gemini call behind the classifier + resolver
+ route interfaces the existing pipeline already calls (Part 11 §7.1).

Injected as BOTH `classifier` and `resolver` into CognitiveAnalyzer, so
`analyze()` runs unchanged (§6): it calls `.classify()` then `.resolve()`, whose
scores flow into the untouched `derive_*`/`apply_deltas` math. The front door
calls `.route()`. All three read ONE memoized Gemini call per utterance.

Duck-typed surface the runtime touches:
    .classify(text, top_evidence=0) -> {"scores", "signals", "evidence"}
    .resolve(text, current_concept) -> resolver-shaped dict (INHERIT -> abstain)
    .route(text, session)           -> RouteResult (intent / safety / answer_attempt)
    .embed(texts)                   -> MiniLM embeddings (retrieval, policy shadow)
    .score_matrix(emb, cues=None)   -> [n, 38] Gemini signal vector (policy shadow)
    .embedder                       -> lazily-loaded MiniLM (HOPE + chunk index)

MiniLM stays loaded for retrieval `S_rel` + HOPE (CLAUDE.md mandate); only the
signal/concept/intent *perception* moves to Gemini.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from . import config
from .route import INHERIT, INTENT_SET, RouteResult
from .build_perception import build as _build_artifacts

try:
    import debug_logger as _dbg
except ImportError:
    _dbg = None  # type: ignore[assignment]


def _clamp01(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def fuse_primary(primary: str, secondaries: Sequence[str], scores_row: np.ndarray,
                 concept_ids: Sequence[str], tau: float) -> str:
    """§5.5 hybrid cross-check (pure, shared with eval): promote the resolver's
    confident top-1 to primary IFF it already sits in Gemini's {primary+secondaries}
    set. Never introduces a concept Gemini didn't consider; never overrides INHERIT."""
    if primary == INHERIT or scores_row is None:
        return primary
    j = int(np.argmax(scores_row))
    if float(scores_row[j]) < tau:          # resolver abstains -> keep Gemini's pick
        return primary
    top = concept_ids[j]
    return top if top in ([primary] + list(secondaries)) else primary


class GeminiPerception:
    """See module docstring. `call_fn` is injectable for offline tests:
    call_fn(prompt: str, system: str) -> dict | None (parsed perception or None)."""

    def __init__(
        self,
        enums: Optional[dict] = None,
        context: Optional[str] = None,
        *,
        call_fn: Optional[Callable[[str, str], Optional[dict]]] = None,
        signal_threshold: float = config.PERCEPTION_SIGNAL_THRESHOLD,
        device: Optional[str] = None,
        cache_size: int = 512,
    ) -> None:
        if enums is None or context is None:
            built = _load_or_build()
            enums = enums or built["enums"]
            context = context or built["context"]
        self.enums = enums
        self.context = context
        self.labels: List[str] = enums["labels"]
        self.concept_ids: List[str] = enums["concept_ids"]
        self._catalog = set(self.concept_ids) | {INHERIT}
        self._label_index = {l: i for i, l in enumerate(self.labels)}
        self.signal_threshold = signal_threshold
        self._call_fn = call_fn
        self._device = device
        self._embedder = None
        self._embedder_lock = threading.Lock()
        self._schema = None
        self._cache: Dict[str, dict] = {}
        self._cache_order: List[str] = []
        self._cache_size = cache_size
        self._last_single_text: Optional[str] = None
        self._processor = None
        self._anchors = None   # lazy (anchor_emb, concept_ids, concept_names) for candidate hints
        self._xresolver = None  # lazy ConceptResolver for the §5.5 cross-check (shares MiniLM)
        self._cc_resolved = False   # Stage 5 context cache, resolved once per process
        self._cc_name: Optional[str] = None
        # Part 13 diagnostics: per-turn sub-timings (ms). The server's single
        # `perception` counter cannot say whether a slow turn was the Gemini
        # round-trip, the MiniLM candidate hints, or the §5.5 cross-check —
        # all three live inside it. Reset by timing_reset(), read after the turn.
        self.timing: Dict[str, int] = {}

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, **kwargs) -> "GeminiPerception":
        return cls(**kwargs)

    # -------------------------------------------------------------- embedder
    @property
    def embedder(self):
        """Lazily-loaded MiniLM — shared with HOPE + the chunk index (one model
        in VRAM), exactly as the retired classifier's embedder was.

        Locked: the tutor's background prewarm thread and the first turn can
        race into this property, and two concurrent SentenceTransformer
        constructions corrupt each other via accelerate's global
        init_empty_weights state ("Cannot copy out of meta tensor") — both
        loads then fail. Single-flight construction fixes it.
        """
        if self._embedder is None:
            with self._embedder_lock:
                if self._embedder is None:
                    from cognitive_classifier.classifier import MODEL_NAME
                    from sentence_transformers import SentenceTransformer

                    self._embedder = SentenceTransformer(MODEL_NAME, device=self._device)
        return self._embedder

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        texts = list(texts)
        if len(texts) == 1:
            # the policy shadow calls embed([norm]) then score_matrix(emb); record
            # the text so score_matrix can recover the memoized Gemini scores.
            self._last_single_text = texts[0]
        return np.asarray(
            self.embedder.encode(texts, normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32,
        )

    # ----------------------------------------------------------- normalize
    def _normalize(self, text: str) -> str:
        if self._processor is None:
            from cognitive_input_processor.input_processor import InputProcessor
            self._processor = InputProcessor()
        return self._processor.normalize_input(text or "")

    # ------------------------------------------------------------- perceive
    def timing_reset(self) -> None:
        """Start a fresh per-turn sub-timing ledger (Part 13 diagnostics)."""
        self.timing = {}

    def _bump(self, key: str, t0: float) -> None:
        self.timing[key] = self.timing.get(key, 0) + int((time.perf_counter() - t0) * 1000)

    def _perceive(self, text: str, session: Optional[dict] = None) -> dict:
        """The ONE Gemini call per utterance, memoized by normalized text so
        route/classify/resolve/score_matrix share a single network round-trip."""
        norm = self._normalize(text)
        cached = self._cache.get(norm)
        if cached is not None:
            self.timing["memo_hits"] = self.timing.get("memo_hits", 0) + 1
            if _dbg:
                _dbg.emit(_dbg.L2, "perception_cache_hit", text_len=len(norm))
            return cached
        if _dbg:
            _dbg.emit(_dbg.L2, "perception_start", text=norm[:120])
        t0 = time.perf_counter()
        raw = self._invoke(norm, session or {})
        self._bump("invoke_ms", t0)
        perception = self._validate(raw)
        # Emit a rich done event with the key decisions from this call
        if _dbg:
            try:
                _intent = perception.get("intent") or (perception.get("route") or {}).get("primary") or "?"
                _concept = perception.get("concept_id") or (perception.get("concept") or {}).get("concept_id") or "?"
                _scores = perception.get("signal_scores") or {}
                _sigs = [k for k, v in _scores.items() if v >= 0.2]
                _gemini_ms = self.timing.get("gemini_ms", 0)
                _dbg.emit(_dbg.L2, "perception_done",
                          intent=_intent, concept=_concept,
                          signals=_sigs,
                          gemini_ms=_gemini_ms,
                          invoke_ms=int((time.perf_counter() - t0) * 1000))
            except Exception:  # noqa: BLE001 — debug must never break perception
                pass
        self._cache[norm] = perception
        self._cache_order.append(norm)
        if len(self._cache_order) > self._cache_size:
            old = self._cache_order.pop(0)
            self._cache.pop(old, None)
        return perception

    def _invoke(self, norm_text: str, session: dict) -> Optional[dict]:
        # Split the two costs: building the prompt pulls MiniLM (candidate hints),
        # the call itself is the network round-trip. They fail very differently.
        t0 = time.perf_counter()
        prompt = self._dynamic_prompt(norm_text, session)
        self._bump("prompt_ms", t0)
        if self._call_fn is not None:
            try:
                return self._call_fn(prompt, self.context)
            except Exception:  # noqa: BLE001 — injected stub failures -> fallback
                return None
        t1 = time.perf_counter()
        try:
            return self._gemini_call(prompt)
        finally:
            self._bump("gemini_ms", t1)

    def _concept_candidates(self, norm_text: str) -> List[tuple]:
        """§5.5 concept hardening: top-K catalog concepts by MiniLM similarity to the
        utterance, injected as `candidate_concepts` hints in the per-turn prompt.
        Reuses the resolver's shipped anchor embeddings + the already-loaded MiniLM.
        Best-effort: any failure returns [] and the call proceeds without hints."""
        if config.PERCEPTION_CANDIDATE_K <= 0 or not norm_text.strip():
            return []
        try:
            if self._anchors is None:
                model_dir = Path(__file__).resolve().parent.parent / "models" / "concept_resolver"
                meta = json.loads((model_dir / "concepts_meta.json").read_text(encoding="utf-8"))
                emb = np.load(model_dir / "anchor_embeddings.npy").astype(np.float32)
                self._anchors = (emb, meta["concept_ids"], meta["concept_names"])
            anchor_emb, ids, names = self._anchors
            # embedder.encode directly — self.embed() would clobber _last_single_text
            q = np.asarray(self.embedder.encode([norm_text], normalize_embeddings=True,
                                                show_progress_bar=False), dtype=np.float32)[0]
            top = np.argsort(-(anchor_emb @ q))[: config.PERCEPTION_CANDIDATE_K]
            return [(ids[int(i)], names[int(i)]) for i in top]
        except Exception:  # noqa: BLE001 — hints are optional; never fail perception on them
            return []

    def topic_candidates(self, text: str, k: int = 3) -> List[tuple]:
        """Public local (free, no Gemini) topic lookup: top-k catalog concepts by
        MiniLM anchor similarity WITH scores — [(concept_id, name, sim), ...].

        Used by the tutor loop's topic-shift handler to ground an explicit topic
        request ("i asked about natural numbers") or a bare topic label that the
        Gemini call abstained on / resolved to the negated mention. Best-effort:
        returns [] on any failure."""
        if not (text or "").strip():
            return []
        try:
            if self._anchors is None:  # same lazy load as _concept_candidates
                model_dir = Path(__file__).resolve().parent.parent / "models" / "concept_resolver"
                meta = json.loads((model_dir / "concepts_meta.json").read_text(encoding="utf-8"))
                emb = np.load(model_dir / "anchor_embeddings.npy").astype(np.float32)
                self._anchors = (emb, meta["concept_ids"], meta["concept_names"])
            anchor_emb, ids, names = self._anchors
            q = np.asarray(self.embedder.encode([text], normalize_embeddings=True,
                                                show_progress_bar=False), dtype=np.float32)[0]
            sims = anchor_emb @ q
            top = np.argsort(-sims)[: max(1, k)]
            return [(ids[int(i)], names[int(i)], float(sims[int(i)])) for i in top]
        except Exception:  # noqa: BLE001 — shift grounding is best-effort
            return []

    def _dynamic_prompt(self, norm_text: str, session: dict) -> str:
        parts = []
        cur = session.get("current_concept")
        if cur:
            parts.append(f"current_concept: {cur}")
        last = session.get("last_action")
        if last:
            parts.append(f"last_tutor_action: {last}")
        pending = session.get("pending_check") or {}
        if pending.get("question"):
            parts.append(f"open_question_awaiting_answer: {pending['question']}")
        ctx = session.get("context") or []
        if ctx:
            hist = "; ".join(f"{h.get('role')}: {h.get('text')}" for h in ctx[-2:])
            parts.append(f"recent: {hist}")
        cands = self._concept_candidates(norm_text)
        if cands:
            parts.append("candidate_concepts (similarity hints, see catalog instructions):\n"
                         + "\n".join(f"  - {cid} = {name}" for cid, name in cands))
        header = ("Classify this one student utterance into the JSON schema. Use the session "
                  "context only to judge concept inheritance and whether it answers the open question.")
        ctx_block = ("\n".join(parts)) if parts else "(no session context yet)"
        return f"{header}\n\nSESSION CONTEXT:\n{ctx_block}\n\nSTUDENT UTTERANCE:\n{norm_text}"

    def _cached_content(self) -> Optional[str]:
        """Stage 5: the Vertex context-cache resource for the static block. Env
        override wins; else the persisted record (expiry + prompt-sha checked).
        Resolved once per process; disabled for the process after a cached call
        fails (server-side expiry) so we never loop on a dead resource."""
        if not self._cc_resolved:
            self._cc_resolved = True
            if config.PERCEPTION_CACHED_CONTENT:
                self._cc_name = config.PERCEPTION_CACHED_CONTENT
            else:
                try:
                    from .vertex_cache import active_name
                    self._cc_name = active_name()
                except Exception:  # noqa: BLE001 — cache is an optimization only
                    self._cc_name = None
        return self._cc_name

    def _gemini_call(self, prompt: str) -> Optional[dict]:
        """Real Vertex path. Hard timeout + parse handled in llm_vertex; any
        failure returns None so _validate falls back (a turn never hard-fails).
        When the Stage 5 context cache is active, a failed cached call is retried
        ONCE with the full system instruction (cache may have expired server-side),
        and the cache is dropped for the rest of the process."""
        import llm_vertex

        cc = self._cached_content()
        for attempt_cc in ([cc, None] if cc else [None]):
            # Count attempts and time each one: a 6 s perception call is either
            # ONE slow round-trip or a failed cached attempt plus a fallback, and
            # those have entirely different fixes.
            self.timing["gem_attempts"] = self.timing.get("gem_attempts", 0) + 1
            self.timing["gem_cached"] = int(attempt_cc is not None)
            _ta = time.perf_counter()
            try:
                result = llm_vertex.generate_json(
                    prompt,
                    response_schema=self._build_schema(),
                    system=(None if attempt_cc else self.context),
                    cached_content=attempt_cc,
                    model=config.VERTEX_PERCEPTION_MODEL,
                    location=config.VERTEX_REGION,
                    timeout_s=config.PERCEPTION_TIMEOUT_S,
                    temperature=0.0,
                )
            except Exception:  # noqa: BLE001 — timeout / transport
                result = None
            self.timing[f"gem_try{self.timing['gem_attempts']}_ms"] = \
                int((time.perf_counter() - _ta) * 1000)
            if result is not None and result.ok:
                return result.data
            if attempt_cc is not None:
                self._cc_name = None          # dead cache -> full prompt from now on
        return None

    def _build_schema(self):
        if self._schema is not None:
            return self._schema
        from google.genai import types

        T = types.Type
        self._schema = types.Schema(
            type=T.OBJECT,
            properties={
                "intent": types.Schema(type=T.STRING, enum=self.enums["intents"]),
                "also_learning": types.Schema(type=T.BOOLEAN),
                "concept_id": types.Schema(type=T.STRING, enum=self.concept_ids + [INHERIT]),
                "concept_confidence": types.Schema(type=T.NUMBER),
                "secondary_concepts": types.Schema(
                    type=T.ARRAY, items=types.Schema(type=T.STRING, enum=self.concept_ids)),
                "signal_scores": types.Schema(
                    type=T.OBJECT,
                    properties={lab: types.Schema(type=T.NUMBER) for lab in self.labels}),
                "answer_attempt": types.Schema(type=T.BOOLEAN),
                "safety": types.Schema(type=T.BOOLEAN),
            },
            required=["intent", "concept_id", "signal_scores", "answer_attempt", "safety"],
        )
        return self._schema

    # ------------------------------------------------------- validation belt
    def _validate(self, raw: Optional[dict]) -> dict:
        """Parse -> coerce every field into its allowed set. On total failure,
        fall back to LEARNING + inherit-concept + neutral signals so the learning
        path degrades gracefully (§5.5a, Stage 4). Gates already own SAFETY/NONSENSE."""
        if not isinstance(raw, dict):
            return self._fallback()
        intent = raw.get("intent")
        if intent not in INTENT_SET:
            return self._fallback()

        cid = raw.get("concept_id")
        if cid not in self._catalog:
            cid = INHERIT
        secondary = [c for c in (raw.get("secondary_concepts") or [])
                     if c in self._catalog and c != INHERIT][:5]

        scores_in = raw.get("signal_scores") or {}
        scores: Dict[str, float] = {}
        if isinstance(scores_in, dict):
            for lab, val in scores_in.items():
                if lab in self._label_index:
                    v = _clamp01(val)
                    if v > 0.0:
                        scores[lab] = v

        return {
            "intent": intent,
            "also_learning": bool(raw.get("also_learning", False)),
            "concept_id": cid,
            "concept_confidence": _clamp01(raw.get("concept_confidence", 0.0)),
            "secondary_concepts": secondary,
            "signal_scores": scores,
            "answer_attempt": bool(raw.get("answer_attempt", False)),
            "safety": bool(raw.get("safety", False)),
            "_source": "gemini",
        }

    def _fallback(self) -> dict:
        return {
            "intent": "LEARNING", "also_learning": False,
            "concept_id": INHERIT, "concept_confidence": 0.0, "secondary_concepts": [],
            "signal_scores": {}, "answer_attempt": False, "safety": False,
            "_source": "fallback",
        }

    # ------------------------------------------------------ classifier role
    def classify(self, text: str, top_evidence: int = 0) -> dict:
        p = self._perceive(text)
        scores = {lab: round(float(p["signal_scores"].get(lab, 0.0)), 4) for lab in self.labels}
        signals = [lab for lab in self.labels if scores[lab] >= self.signal_threshold]
        signals.sort(key=lambda l: -scores[l])
        return {"signals": signals, "scores": scores, "evidence": []}

    def score_matrix(self, query_emb: np.ndarray, query_cues=None) -> np.ndarray:
        """Gemini signal vector [n, 38] in label_space order, for the policy shadow
        feature vector. Uses the text most recently passed to embed() (the shadow's
        call pattern is embed([norm]) immediately before score_matrix(emb))."""
        n = int(query_emb.shape[0]) if getattr(query_emb, "shape", None) else 1
        vec = np.zeros((n, len(self.labels)), dtype=np.float32)
        if self._last_single_text is not None:
            p = self._perceive(self._last_single_text)
            row = np.array([p["signal_scores"].get(l, 0.0) for l in self.labels], dtype=np.float32)
            vec[:] = row
        return vec

    # -------------------------------------------------------- resolver role
    @property
    def crosscheck_resolver(self):
        """Lazily-built ConceptResolver for the §5.5 cross-check, constructed with
        the SHARED MiniLM embedder (never a second SentenceTransformer in memory).
        Mirrors ConceptResolver.load() minus the embedder construction — the
        resolver module itself stays unmodified (Part 11 §14)."""
        if self._xresolver is None and config.PERCEPTION_CONCEPT_CROSSCHECK:
            try:
                from concept_resolver.resolver import ConceptResolver, DEFAULT_MODEL_DIR
                model_dir = Path(DEFAULT_MODEL_DIR)
                meta = json.loads((model_dir / "concepts_meta.json").read_text(encoding="utf-8"))
                rcfg = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
                bank = np.load(model_dir / "train_bank.npz")
                logreg = None
                lr_path = model_dir / "logreg_resolver.npz"
                if lr_path.exists():
                    w = np.load(lr_path)
                    logreg = {"coef": w["coef"], "intercept": w["intercept"], "classes": w["classes"]}
                self._xresolver = ConceptResolver(
                    self.embedder,
                    concept_ids=meta["concept_ids"], concept_names=meta["concept_names"],
                    anchor_emb=np.load(model_dir / "anchor_embeddings.npy"),
                    bank_emb=bank["emb"], bank_concept_matrix=bank["concept_matrix"],
                    alpha=rcfg["alpha"], k=rcfg["k"], tau=rcfg["tau"],
                    method=rcfg.get("method", "blend"), logreg=logreg,
                )
            except Exception:  # noqa: BLE001 — cross-check is best-effort, never fails a turn
                return None
        return self._xresolver

    def _crosscheck(self, text: str, primary: str, secondaries: List[str]) -> str:
        """Apply fuse_primary using the local resolver's scores; best-effort."""
        t0 = time.perf_counter()
        res = self.crosscheck_resolver
        self._bump("xresolver_build_ms", t0)
        if res is None:
            return primary
        t1 = time.perf_counter()
        try:
            row = res.score_texts([self._normalize(text)])[0]
            return fuse_primary(primary, secondaries, row, res.concept_ids, res.tau)
        except Exception:  # noqa: BLE001
            return primary
        finally:
            self._bump("crosscheck_ms", t1)

    def resolve(self, text: str, current_concept: Optional[str] = None, top_k: int = 3) -> dict:
        p = self._perceive(text)
        cid = p["concept_id"]
        conf = round(float(p["concept_confidence"]), 4)
        if cid == INHERIT:
            return {
                "concept_id": current_concept,
                "concept_confidence": conf,
                "secondary_concepts": [],
                "abstained": True,
                "resolution_reason": ("gemini abstained (INHERIT_CURRENT_CONCEPT) -> "
                                      + ("inherited session concept" if current_concept
                                         else "no session concept to inherit")),
            }
        secondaries = list(p["secondary_concepts"])
        fused = self._crosscheck(text, cid, secondaries)
        reason = f"gemini concept pick (confidence {conf:.2f})"
        if fused != cid:
            secondaries = [cid] + [s for s in secondaries if s != fused]
            cid = fused
            reason = f"gemini pick cross-checked -> resolver-preferred '{fused}' (§5.5 hybrid)"
        return {
            "concept_id": cid,
            "concept_confidence": conf,
            "secondary_concepts": secondaries[:max(0, top_k - 1)],
            "abstained": False,
            "resolution_reason": reason,
        }

    # ------------------------------------------------------------ route role
    def route(self, text: str, session: Optional[dict] = None) -> RouteResult:
        p = self._perceive(text, session=session)
        intent = p["intent"]
        return RouteResult(
            primary=intent,
            also_learning=bool(p["also_learning"]),
            safety_alert=bool(p["safety"]) or intent == "SAFETY",
            answer_attempt=bool(p["answer_attempt"]),
            concept_id=(None if p["concept_id"] == INHERIT else p["concept_id"]),
            concept_confidence=float(p["concept_confidence"]),
            secondary_concepts=list(p["secondary_concepts"]),
            signal_scores=dict(p["signal_scores"]),
            source=p.get("_source", "gemini"),
            reason="gemini perception" if p.get("_source") == "gemini" else "perception fallback (LEARNING/inherit)",
            raw=p,
        )


# --------------------------------------------------------------------------- #
_ARTIFACTS: Optional[dict] = None


def _load_or_build() -> dict:
    """Read the built enums + cached context, building them if absent/stale."""
    global _ARTIFACTS
    if _ARTIFACTS is not None:
        return _ARTIFACTS
    enums_path = config.BUILD_DIR / "perception_enums.json"
    ctx_path = config.BUILD_DIR / "perception_context.md"
    if enums_path.exists() and ctx_path.exists():
        _ARTIFACTS = {
            "enums": json.loads(enums_path.read_text(encoding="utf-8")),
            "context": ctx_path.read_text(encoding="utf-8"),
        }
    else:
        built = _build_artifacts(write=True)
        _ARTIFACTS = {"enums": built["enums"], "context": built["context"]}
    return _ARTIFACTS
