"""Grounded evidence selection behind the Retrieval Feature Module Interface."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

import numpy as np
import networkx as nx

from query import (
    Snapshot,
    bridge_evidence,
    cohesion_filter,
    ev,
    mastery_to_band,
    misconception_evidence,
    need_evidence,
    snapshot_rerank,
)
from runtime.contracts import (
    FailureSeverity,
    FailureSignal,
    ModuleOutcome,
    StateChange,
    StateOperation,
    StateScope,
    TurnInput,
    deep_freeze,
)


CAPABILITY = "retrieval"
ASSESSING_ACTIONS = frozenset({
    "MISCONCEPTION_PROBE", "ISOMORPHIC_PRACTICE", "COMPLETION_STEP",
    "TRANSFER_PROBLEM", "TEST_QUESTION",
})


@dataclass(frozen=True)
class RetrievalStateView:
    """Immutable learner facts Retrieval may observe; no state object crosses the seam."""

    mastery: Mapping[str, float] = field(default_factory=dict)
    measured_concepts: frozenset[str] = frozenset()
    misconceptions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    representations_known: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    served_items: tuple[str, ...] = ()
    bridges_served: tuple[str, ...] = ()
    hint_progress: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    hope_rolling: Mapping[str, float] = field(default_factory=dict)
    concept_metadata: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    pending_assessment: bool = False

    def __post_init__(self) -> None:
        for name in ("mastery", "misconceptions", "representations_known",
                     "hint_progress", "hope_rolling", "concept_metadata"):
            object.__setattr__(self, name, deep_freeze(getattr(self, name)))
        object.__setattr__(self, "measured_concepts", frozenset(self.measured_concepts))
        object.__setattr__(self, "served_items", tuple(self.served_items))
        object.__setattr__(self, "bridges_served", tuple(self.bridges_served))

    # Snapshot-compatible read port.
    def mastery_value(self, concept_id: str | None) -> float:
        return float(self.mastery.get(str(concept_id), 0.2))

    def has_measured_mastery(self, concept_id: str) -> bool:
        return concept_id in self.measured_concepts

    def is_known(self, concept_id: str) -> bool:
        return concept_id in self.mastery or concept_id in self.concept_metadata

    def hint_dependency(self, concept_id: str) -> float:
        row = self.hint_progress.get(concept_id) or self.concept_metadata.get(concept_id) or {}
        return max(0.0, min(1.0, float(row.get("hint_dependency", 0.0))))

    def representations_missing(self, concept_id: str, available: Sequence[str]):
        return tuple(rep for rep in available
                     if rep not in set(self.representations_known.get(concept_id, ())))

    def misconception_status(self, misconception_id: str) -> str:
        return str((self.misconceptions.get(misconception_id) or {}).get("status", "untracked"))

    def misconception_failures(self, misconception_id: str) -> int:
        return int((self.misconceptions.get(misconception_id) or {}).get(
            "consecutive_failures", 0))

    def should_serve_bridge(self, bridge_id: str, zpd_center: float) -> bool:
        return (bridge_id not in self.bridges_served
                and self.mastery_value(bridge_id) < 0.6 and zpd_center < 7.0)

    @property
    def hope(self) -> dict[str, float]:
        return {key: float(self.hope_rolling.get(key, 0.5)) for key in ("KI", "KT", "CT")}

    def cold_recall_strength(self, concept_id: str):
        value = (self.concept_metadata.get(concept_id) or {}).get("cold_recall_strength")
        return None if value is None else float(value)

    def confidence_trend(self, concept_id: str) -> str:
        history = (self.concept_metadata.get(concept_id) or {}).get("item_history") or {}
        outcomes = []
        for _, row in sorted(history.items(), key=lambda item: (item[1] or {}).get(
                "last_seen") or ""):
            outcomes.extend((row or {}).get("outcomes") or ())
        values = [1.0 if value == "correct" else 0.5 if value == "partial" else 0.0
                  for value in outcomes[-6:]]
        if len(values) < 3:
            return "unknown"
        half = len(values) // 2
        delta = (sum(values[-half:]) / half) - (sum(values[:half]) / half)
        return "rising" if delta > 0.15 else "falling" if delta < -0.15 else "flat"

    def transfer_readiness(self, concept_id: str) -> float:
        if concept_id not in self.measured_concepts:
            return 0.0
        score = 0.6 * self.mastery_value(concept_id) + 0.4 * (
            1.0 - self.hint_dependency(concept_id))
        cold = self.cold_recall_strength(concept_id)
        if cold is not None:
            score = 0.7 * score + 0.3 * cold
        return round(max(0.0, min(1.0, score)), 4)

    def hint_chain_position(self, concept_id: str) -> int:
        return int((self.hint_progress.get(concept_id) or {}).get("hints_used", 0))

    def metacognitive_when(self, concept_id: str) -> str:
        struggling = bool((self.concept_metadata.get(concept_id) or {}).get("struggling"))
        return "after_struggle" if struggling else "after_success"


class _SnapshotStateAdapter:
    """Names expected by the proven query.py ranking functions."""

    def __init__(self, view: RetrievalStateView) -> None:
        self._view = view
        self.concept_states = view.concept_metadata
        self.served_items = view.served_items
        self.hope_rolling = view.hope

    def mastery(self, concept_id): return self._view.mastery_value(concept_id)
    def has_measured_mastery(self, concept_id): return self._view.has_measured_mastery(concept_id)
    def is_known(self, concept_id): return self._view.is_known(concept_id)
    def hint_dependency(self, concept_id): return self._view.hint_dependency(concept_id)
    def representations_missing(self, concept_id, available):
        return self._view.representations_missing(concept_id, available)
    def misconception_status(self, misconception_id):
        return self._view.misconception_status(misconception_id)
    def misconception_failures(self, misconception_id):
        return self._view.misconception_failures(misconception_id)
    def should_serve_bridge(self, bridge_id, center):
        return self._view.should_serve_bridge(bridge_id, center)
    def cold_recall_strength(self, concept_id): return self._view.cold_recall_strength(concept_id)
    def confidence_trend(self, concept_id): return self._view.confidence_trend(concept_id)
    def transfer_readiness(self, concept_id): return self._view.transfer_readiness(concept_id)
    def hint_chain_position(self, concept_id): return self._view.hint_chain_position(concept_id)
    def metacognitive_when(self, concept_id): return self._view.metacognitive_when(concept_id)


@dataclass(frozen=True)
class RetrievalStoreView:
    concepts: tuple[Mapping[str, Any], ...] = ()
    chunks: tuple[Mapping[str, Any], ...] = ()
    graph: Any = None
    chunk_embeddings: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "concepts", tuple(deep_freeze(v) for v in self.concepts))
        object.__setattr__(self, "chunks", tuple(deep_freeze(v) for v in self.chunks))
        if self.graph is not None:
            object.__setattr__(self, "graph", nx.freeze(copy.deepcopy(self.graph)))
        if self.chunk_embeddings is not None:
            values = np.array(self.chunk_embeddings, dtype=float, copy=True)
            values.setflags(write=False)
            object.__setattr__(self, "chunk_embeddings", values)


@dataclass(frozen=True)
class RetrievalRequest:
    turn_input: TurnInput
    concept_id: str | None
    concept_confidence: float
    secondary_concepts: tuple[str, ...]
    pedagogical: Any
    state: RetrievalStateView
    store: RetrievalStoreView
    perception_uncertain: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "secondary_concepts", tuple(self.secondary_concepts))


@dataclass(frozen=True)
class GroundedEvidence:
    id: str
    type: str
    why: str
    content: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.type or not self.why:
            raise ValueError("grounded evidence requires id, type, and provenance reason")
        object.__setattr__(self, "content", deep_freeze(self.content))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "why": self.why,
                **{key: value for key, value in self.content.items()}}


@dataclass(frozen=True)
class GroundedManifest:
    evidence: tuple[GroundedEvidence, ...]
    bridge_ids: tuple[str, ...]
    schema_ids: tuple[str, ...]
    ranking_trace: Mapping[str, Any]
    cohesion_log: tuple[str, ...]
    snapshot: Mapping[str, Any]
    band_reason: str
    grounding: str
    need: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "bridge_ids", tuple(self.bridge_ids))
        object.__setattr__(self, "schema_ids", tuple(self.schema_ids))
        object.__setattr__(self, "ranking_trace", deep_freeze(self.ranking_trace))
        object.__setattr__(self, "cohesion_log", tuple(self.cohesion_log))
        object.__setattr__(self, "snapshot", deep_freeze(self.snapshot))

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": [item.to_dict() for item in self.evidence],
            "bridge_ids": list(self.bridge_ids), "schema_ids": list(self.schema_ids),
            "ranking_trace": dict(self.ranking_trace),
            "cohesion_log": list(self.cohesion_log), "snapshot": dict(self.snapshot),
            "band_reason": self.band_reason, "grounding": self.grounding,
        }


@dataclass(frozen=True)
class RetrievalResult:
    manifest: GroundedManifest
    assessment_candidate: Mapping[str, Any] | None = None
    assessment_allowed: bool = True
    query_embedding: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.assessment_candidate is not None:
            object.__setattr__(self, "assessment_candidate", deep_freeze(
                self.assessment_candidate))


@dataclass(frozen=True)
class RetrievalDependencies:
    embed: Callable[[Sequence[str]], Any] | None = None
    cohesion_check: Callable[[list[dict[str, Any]]], Sequence[str] | None] | None = None
    prepare_assessment: Callable[[RetrievalRequest, list[dict[str, Any]], Any],
                                 Mapping[str, Any] | None] | None = None


class RetrievalInterface(Protocol):
    def retrieve(self, request: RetrievalRequest) -> ModuleOutcome[RetrievalResult]: ...


class Retrieval:
    """Select and provenance evidence without writing learner or session state."""

    def __init__(self, dependencies: RetrievalDependencies | None = None) -> None:
        self._dependencies = dependencies or RetrievalDependencies()

    def retrieve(self, request: RetrievalRequest) -> ModuleOutcome[RetrievalResult]:
        invalid = self._validate_store(request)
        if invalid is not None:
            return self._safe_empty(request, invalid)
        if self._dependencies.embed is None or request.store.chunk_embeddings is None:
            return self._safe_empty(request, self._failure(
                request, "embeddings_unavailable", "embedding"))
        try:
            return self._retrieve(request)
        except (ValueError, TypeError, KeyError) as exc:
            return self._safe_empty(request, self._failure(
                request, "invalid_evidence", "validation", str(exc)))
        except Exception as exc:
            return self._safe_empty(request, self._failure(
                request, "embeddings_unavailable", "embedding", str(exc)))

    def _retrieve(self, request: RetrievalRequest) -> ModuleOutcome[RetrievalResult]:
        graph = request.store.graph
        chunks = [dict(row) for row in request.store.chunks]
        concepts = {str(row["concept_id"]): dict(row) for row in request.store.concepts}
        chunks_by_id = {str(row["chunk_id"]): row for row in chunks}
        concept_ids = tuple(filter(None, (request.concept_id, *request.secondary_concepts)))
        learner = _SnapshotStateAdapter(request.state)
        primary = request.concept_id
        mastery = request.state.mastery_value(primary)
        band = mastery_to_band(mastery)
        band_reason = ("learner state (measured)" if primary in request.state.measured_concepts
                       else "cold start") + f", mastery({primary})={mastery:.2f}"
        snapshot = Snapshot(learner, primary, concepts.get(primary), graph, band)
        need = str(request.pedagogical.need)
        text = str(request.turn_input.interaction.get("text") or "")

        def similarity(value: str) -> float:
            query = np.asarray(self._dependencies.embed([text]), dtype=float)
            candidate = np.asarray(self._dependencies.embed([value[:400]]), dtype=float)
            return float((query @ candidate.T)[0][0])

        evidence = bridge_evidence(
            graph, chunks_by_id, snapshot, list(concept_ids), need == "bridge",
            relevance=lambda bridge_id, node: similarity(" ".join(filter(None, (
                str(node.get("name") or bridge_id),
                str(node.get("diagnostic_question") or ""),
            )))),
        )
        evidence += misconception_evidence(graph, snapshot)
        evidence += need_evidence(graph, concepts, snapshot, need, None)
        if (request.pedagogical.action == "MISCONCEPTION_PROBE" and primary in graph
                and not any(item["type"] == "misconception" for item in evidence)):
            self._insert_candidate_probe(evidence, request, graph)

        candidate_indices = [index for index, row in enumerate(chunks)
                             if set(row.get("concept_ids") or ()) & set(concept_ids)]
        if not candidate_indices:
            candidate_indices = list(range(len(chunks)))
        query_embedding = np.asarray(self._dependencies.embed([text]), dtype=float)
        embeddings = request.store.chunk_embeddings
        if embeddings.ndim != 2 or embeddings.shape[0] != len(chunks):
            raise ValueError("chunk embedding shape does not match evidence store")
        similarities = (query_embedding @ embeddings[candidate_indices].T)[0]
        order = np.argsort(-similarities)[:24]
        ranked = [dict(chunks[candidate_indices[index]],
                       score=float(max(similarities[index], 0.0))) for index in order]
        figures = {node: attrs.get("disambiguates_misconceptions") or []
                   for node, attrs in graph.nodes(data=True) if attrs.get("image_path")}
        top, trace = snapshot_rerank(ranked, snapshot, need, 6, figures)
        evidence.extend(ev(row["chunk_id"], "chunk",
                           f"local semantic+pedagogic match (role={row.get('pedagogical_role')})",
                           image_path=(row.get("image_path")
                                       if row.get("kind") == "figure_caption" else None))
                        for row in top)
        cohesion_log = cohesion_filter(graph, evidence, chunks, list(concept_ids),
                                       band[2], None, use_judge=False)
        if self._dependencies.cohesion_check is not None:
            try:
                extra = self._dependencies.cohesion_check(evidence)
                cohesion_log.extend(extra or ())
            except Exception as exc:
                failure = self._failure(request, "cohesion_failure", "cohesion", str(exc))
                return self._safe_empty(request, failure)

        typed = tuple(GroundedEvidence(
            id=str(item.pop("id")), type=str(item.pop("type")),
            why=str(item.pop("why")), content=item,
        ) for item in (dict(row) for row in evidence))
        manifest = GroundedManifest(
            evidence=typed,
            bridge_ids=tuple(item.id for item in typed if item.type.startswith("bridge")),
            schema_ids=tuple(item.id for item in typed if item.type == "problem_schema"),
            ranking_trace=trace, cohesion_log=tuple(cohesion_log),
            snapshot=snapshot.summary(), band_reason=band_reason,
            grounding=("method_only" if request.pedagogical.action == "SOLVE_STUDENT_PROBLEM"
                       else "manifest_only"), need=need,
        )
        assessment = (
            self._dependencies.prepare_assessment(request, evidence, graph)
            if self._dependencies.prepare_assessment is not None else None
        )
        allowed = not request.perception_uncertain and (
            request.pedagogical.action not in ASSESSING_ACTIONS or assessment is not None)
        changes = self._served_changes(request, typed)
        return ModuleOutcome(value=RetrievalResult(
            manifest=manifest, assessment_candidate=assessment,
            assessment_allowed=allowed,
            query_embedding=tuple(float(value) for value in query_embedding[0]),
        ), state_changes=changes)

    @staticmethod
    def _insert_candidate_probe(evidence, request, graph) -> None:
        for _, misconception_id, edge in graph.out_edges(request.concept_id, data=True):
            if edge.get("relation") != "has_misconception":
                continue
            if request.state.misconception_status(misconception_id) not in {
                    "untracked", "candidate", "weakening"}:
                continue
            node = graph.nodes[misconception_id]
            if node.get("diagnostic_question"):
                evidence.insert(0, ev(
                    misconception_id, "misconception",
                    "suspected via analyzer; diagnostic served (probe-first)",
                    diagnostic_question=node.get("diagnostic_question"),
                    hint_chain=node.get("hint_chain"),
                ))
                return

    @staticmethod
    def _served_changes(request, evidence):
        ids = tuple(dict.fromkeys(item.id for item in evidence))
        if not ids:
            return ()
        changes = [StateChange(
            change_id=f"{request.turn_input.turn_id}:retrieval:served",
            owner=CAPABILITY, scope=StateScope.SESSION, path=("served_items",),
            operation=StateOperation.SET,
            value=tuple(dict.fromkeys((*request.state.served_items, *ids))),
        )]
        bridges = tuple(dict.fromkeys(
            item.id for item in evidence if item.type == "bridge_diagnostic"
        ))
        if bridges:
            changes.append(StateChange(
                change_id=f"{request.turn_input.turn_id}:retrieval:bridges",
                owner=CAPABILITY, scope=StateScope.SESSION,
                path=("bridges_served",), operation=StateOperation.SET,
                value=tuple(dict.fromkeys((*request.state.bridges_served, *bridges))),
            ))
        return tuple(changes)

    def _validate_store(self, request):
        store = request.store
        if store.graph is None or not store.concepts or not store.chunks:
            return self._failure(request, "missing_store", "store")
        for concept in store.concepts:
            if not concept.get("concept_id"):
                return self._failure(request, "invalid_evidence", "validation")
        for chunk in store.chunks:
            if not chunk.get("chunk_id") or not chunk.get("text"):
                return self._failure(request, "invalid_evidence", "validation")
        return None

    @staticmethod
    def _failure(request, cause, phase, detail=""):
        return FailureSignal(
            capability=CAPABILITY, phase=phase, severity=FailureSeverity.DEGRADED,
            recoverable=True, cause=cause, valid_outcome=True,
            context={"turn_id": request.turn_input.turn_id, "detail": detail},
        )

    def _safe_empty(self, request, failure):
        manifest = GroundedManifest(
            evidence=(), bridge_ids=(), schema_ids=(), ranking_trace={},
            cohesion_log=(failure.cause,), snapshot={}, band_reason=failure.cause,
            grounding="manifest_only", need=str(request.pedagogical.need),
        )
        return ModuleOutcome(value=RetrievalResult(
            manifest=manifest, assessment_candidate=None, assessment_allowed=False,
        ), failures=(failure,))
