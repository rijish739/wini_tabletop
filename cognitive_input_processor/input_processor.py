"""Input processor for the Wini cognitive-state tutoring pipeline.

This module prepares a student utterance for downstream cognitive analysis.
It is intentionally split into two layers:

1. Deterministic normalization
   - Clean the text without changing its meaning.
   - Preserve equations, symbols, and scientific notation.

2. Multi-signal semantic tagging
   - Detect whether the utterance contains a question, answer attempt,
     explanation, confusion marker, misconception clue, transfer attempt,
     or topic shift.
   - Return probabilities / scores for each signal instead of forcing a
     single label too early.

The output is meant to feed the cognitive analyzer / pedagogy engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple
import re
import unicodedata


# -----------------------------------------------------------------------------
# Data models
# -----------------------------------------------------------------------------


@dataclass
class InputSignalScores:
    """Multi-label signal scores for a student utterance.

    Scores are floats in the range [0.0, 1.0]. They are not mutually exclusive.
    A single student message may trigger several signals at once.
    """

    question: float = 0.0
    answer_attempt: float = 0.0
    explanation: float = 0.0
    confusion: float = 0.0
    misconception_clue: float = 0.0
    transfer_attempt: float = 0.0
    topic_shift: float = 0.0
    self_correction: float = 0.0
    curiosity: float = 0.0


@dataclass
class ProcessedInput:
    """Canonical output produced by the input processor."""

    raw_text: str
    normalized_text: str
    tokens: List[str]
    signals: InputSignalScores
    candidate_concepts: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the processed object into a JSON-serializable dictionary."""
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "tokens": list(self.tokens),
            "signals": asdict(self.signals),
            "candidate_concepts": list(self.candidate_concepts),
            "metadata": dict(self.metadata),
        }


# -----------------------------------------------------------------------------
# Semantic classifier interface
# -----------------------------------------------------------------------------


class SemanticClassifier(Protocol):
    """Interface for optional semantic signal classification.

    The input processor can work with a deterministic fallback if no classifier
    is provided. In the production stack, this can be implemented with an
    embedder-backed exemplar classifier (for example, MiniLM + cosine over
    exemplar phrases).
    """

    def score(self, text: str, labels: Sequence[str]) -> Dict[str, float]:
        """Return scores for the requested labels.

        The return value should map each label to a confidence in [0.0, 1.0].
        """
        ...


class HeuristicSemanticClassifier:
    """Very small fallback scorer for local testing.

    This is intentionally conservative. It is not a replacement for the real
    semantic classifier; it just allows the module to run in environments where
    the embedder-based classifier is not yet wired in.
    """

    QUESTION_MARKERS = {
        "what", "why", "how", "when", "where", "which", "who", "whom",
        "can", "could", "should", "would", "is", "are", "do", "does",
        "did", "will", "may", "might"
    }

    EXPLANATION_MARKERS = {
        "because", "since", "so", "therefore", "that is why", "in other words",
        "means", "this means", "for example"
    }

    CONFUSION_MARKERS = {
        "confused", "i do not understand", "don't understand", "not sure",
        "i am stuck", "stuck", "lost", "unclear", "why does", "how come"
    }

    TRANSFER_MARKERS = {
        "like", "similar", "same as", "reminds me of", "can i use", "instead",
        "another way", "different chapter", "previous chapter", "previous topic"
    }

    TOPIC_SHIFT_MARKERS = {
        "by the way", "also", "another thing", "on a different topic",
        "switching", "new question", "what about"
    }

    MISCONCEPTION_MARKERS = {
        "always", "never", "infinite current", "voltage flows", "current flows",
        "equals means answer", "moving terms changes sign"
    }

    SELF_CORRECTION_MARKERS = {
        "i think i was wrong", "actually", "wait", "sorry", "let me correct",
        "i mean", "maybe not"
    }

    CURIOUSITY_MARKERS = {
        "what if", "why", "how", "can we", "could we", "is it possible",
        "does it mean", "what happens if"
    }

    def score(self, text: str, labels: Sequence[str]) -> Dict[str, float]:
        lowered = text.lower()
        out: Dict[str, float] = {}

        for label in labels:
            if label == "question":
                out[label] = self._score_question(lowered)
            elif label == "answer_attempt":
                out[label] = self._score_answer_attempt(lowered)
            elif label == "explanation":
                out[label] = self._score_keywords(lowered, self.EXPLANATION_MARKERS)
            elif label == "confusion":
                out[label] = self._score_keywords(lowered, self.CONFUSION_MARKERS)
            elif label == "misconception_clue":
                out[label] = self._score_keywords(lowered, self.MISCONCEPTION_MARKERS)
            elif label == "transfer_attempt":
                out[label] = self._score_keywords(lowered, self.TRANSFER_MARKERS)
            elif label == "topic_shift":
                out[label] = self._score_keywords(lowered, self.TOPIC_SHIFT_MARKERS)
            elif label == "self_correction":
                out[label] = self._score_keywords(lowered, self.SELF_CORRECTION_MARKERS)
            elif label == "curiosity":
                out[label] = self._score_keywords(lowered, self.CURIOUSITY_MARKERS)
            else:
                out[label] = 0.0
        return out

    def _score_keywords(self, lowered: str, markers: Sequence[str]) -> float:
        score = 0.0
        for marker in markers:
            if marker in lowered:
                score = max(score, 0.8)
        return score

    def _score_question(self, lowered: str) -> float:
        if "?" in lowered:
            return 0.95
        first_token = lowered.strip().split(" ", 1)[0] if lowered.strip() else ""
        if first_token in self.QUESTION_MARKERS:
            return 0.7
        if any(marker in lowered for marker in ["why", "what if", "how", "can i", "could i"]):
            return 0.75
        return 0.0

    def _score_answer_attempt(self, lowered: str) -> float:
        # A rough fallback: statements that contain declarative reasoning markers
        # or a direct answer pattern may be answer attempts.
        if any(marker in lowered for marker in ["i think", "my answer", "it is", "because", "therefore"]):
            return 0.65
        return 0.0


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------


@dataclass
class InputProcessorConfig:
    """Configuration for the input processor."""

    lowercase_for_analysis: bool = True
    preserve_raw_text: bool = True
    max_tokens: int = 256
    enable_unicode_nfkc: bool = True
    collapse_whitespace: bool = True
    strip_zero_width_chars: bool = True
    preserve_math_symbols: bool = True
    semantic_threshold: float = 0.35
    concept_keyword_window: int = 8
    # Candidate concept names or identifiers known to the system.
    concept_lexicon: List[str] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Input processor
# -----------------------------------------------------------------------------


class InputProcessor:
    """Prepare a student utterance for cognitive and pedagogical inference.

    The processor performs lightweight, deterministic normalization and then
    extracts multiple semantic signals.
    """

    # Minimal cleanup patterns. These are intentionally conservative.
    _MULTI_SPACE_RE = re.compile(r"\s+")
    _EXTRA_SPACE_AROUND_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
    _SPACE_AFTER_OPEN_PAREN_RE = re.compile(r"([\(\[\{])\s+")
    _SPACE_BEFORE_CLOSE_PAREN_RE = re.compile(r"\s+([\)\]\}])")
    _ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200D\uFEFF]")

    # Lightweight question / reasoning patterns.
    _QUESTION_RE = re.compile(
        r"\b(what|why|how|when|where|which|who|whom|can|could|should|would|is|are|do|does|did|will|may|might)\b",
        re.IGNORECASE,
    )
    _ANSWER_RE = re.compile(
        r"\b(i think|my answer|it is|the answer is|because|therefore|so)\b",
        re.IGNORECASE,
    )
    _EXPLANATION_RE = re.compile(
        r"\b(because|since|therefore|that is why|in other words|for example|means)\b",
        re.IGNORECASE,
    )
    _CONFUSION_RE = re.compile(
        r"\b(confused|don't understand|do not understand|not sure|stuck|lost|unclear)\b",
        re.IGNORECASE,
    )
    _TRANSFER_RE = re.compile(
        r"\b(similar|same as|like|can i use|another way|instead|previous chapter|previous topic)\b",
        re.IGNORECASE,
    )
    _TOPIC_SHIFT_RE = re.compile(
        r"\b(by the way|another thing|new question|switching topics|what about)\b",
        re.IGNORECASE,
    )
    _SELF_CORRECTION_RE = re.compile(
        r"\b(actually|wait|sorry|let me correct|i mean|maybe not|i was wrong)\b",
        re.IGNORECASE,
    )
    _MISCONCEPTION_RE = re.compile(
        r"\b(infinite current|voltage flows|current flows|equals means answer|moving terms changes sign)\b",
        re.IGNORECASE,
    )
    _CURIOUSITY_RE = re.compile(
        r"\b(what if|why|how come|can we|could we|is it possible|what happens if)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        config: Optional[InputProcessorConfig] = None,
        classifier: Optional[SemanticClassifier] = None,
    ) -> None:
        self.config = config or InputProcessorConfig()
        self.classifier: SemanticClassifier = classifier or HeuristicSemanticClassifier()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, text: str, *, session_context: Optional[Mapping[str, Any]] = None) -> ProcessedInput:
        """Process one student message.

        Parameters
        ----------
        text:
            Raw student utterance.
        session_context:
            Optional contextual metadata, for example current concept, recent
            turns, previous misconceptions, or active chapter.

        Returns
        -------
        ProcessedInput
            Canonicalized text, tokens, multi-label signal scores, and candidate
            concepts.
        """
        raw_text = text or ""
        normalized_text = self.normalize_input(raw_text)
        analysis_text = normalized_text.lower() if self.config.lowercase_for_analysis else normalized_text
        tokens = self._tokenize(analysis_text)

        # Step 1: Deterministic feature extraction.
        heuristic_scores = self._heuristic_signal_scores(analysis_text)

        # Step 2: Semantic signal extraction.
        requested_labels = [
            "question",
            "answer_attempt",
            "explanation",
            "confusion",
            "misconception_clue",
            "transfer_attempt",
            "topic_shift",
            "self_correction",
            "curiosity",
        ]
        semantic_scores = self.classifier.score(analysis_text, requested_labels)

        # Step 3: Merge deterministic and semantic scores.
        merged = self._merge_scores(heuristic_scores, semantic_scores)

        # Step 4: Resolve candidate concepts using the current context and the
        # concept lexicon. This is intentionally lightweight; the real concept
        # resolver may be a separate service.
        candidate_concepts = self._extract_candidate_concepts(
            analysis_text,
            session_context=session_context,
        )

        # Step 5: Construct metadata that downstream components can use.
        metadata: Dict[str, Any] = {
            "token_count": len(tokens),
            "char_count": len(normalized_text),
            "has_question_mark": "?" in raw_text,
            "contains_formula": self._contains_formula(normalized_text),
            "contains_numbers": bool(re.search(r"\d", normalized_text)),
            "context_current_concept": (session_context or {}).get("current_concept"),
            "context_active_chapter": (session_context or {}).get("active_chapter"),
        }

        return ProcessedInput(
            raw_text=raw_text,
            normalized_text=normalized_text,
            tokens=tokens,
            signals=merged,
            candidate_concepts=candidate_concepts,
            metadata=metadata,
        )

    def normalize_input(self, text: str) -> str:
        """Normalize the input without changing its meaning.

        Normalization here means cleaning surface noise while preserving the
        semantic content of the student's utterance.

        Safe operations performed:
        - Unicode normalization (NFKC) to standardize visually equivalent forms
        - removal of zero-width characters
        - collapsing repeated whitespace
        - trimming leading/trailing spaces
        - removing accidental spaces before punctuation
        - removing accidental spaces just inside brackets

        Important:
        - We do NOT paraphrase.
        - We do NOT lower-case the preserved raw string here.
        - We do NOT remove mathematical symbols or equations.
        - We do NOT rewrite student meaning.
        """
        if text is None:
            return ""

        normalized = text

        if self.config.enable_unicode_nfkc:
            normalized = unicodedata.normalize("NFKC", normalized)

        if self.config.strip_zero_width_chars:
            normalized = self._ZERO_WIDTH_RE.sub("", normalized)

        # Preserve equations and symbols; only remove obvious spacing noise.
        normalized = self._EXTRA_SPACE_AROUND_PUNCT_RE.sub(r"\1", normalized)
        normalized = self._SPACE_AFTER_OPEN_PAREN_RE.sub(r"\1", normalized)
        normalized = self._SPACE_BEFORE_CLOSE_PAREN_RE.sub(r"\1", normalized)

        if self.config.collapse_whitespace:
            normalized = self._MULTI_SPACE_RE.sub(" ", normalized)

        normalized = normalized.strip()
        return normalized

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize conservatively for analysis.

        This keeps symbols attached to tokens where possible, because equations
        and technical expressions matter in math/science tutoring.
        """
        if not text:
            return []

        # Split on whitespace only; do not aggressively strip punctuation from
        # math expressions like 'V=IR' or '2x+3'.
        tokens = [tok for tok in text.split(" ") if tok]
        if self.config.max_tokens > 0:
            return tokens[: self.config.max_tokens]
        return tokens

    def _heuristic_signal_scores(self, text: str) -> InputSignalScores:
        """Compute deterministic fallback scores from simple textual cues."""
        question = 0.0
        if "?" in text:
            question = 0.95
        elif self._QUESTION_RE.search(text):
            question = 0.7

        answer_attempt = 0.0
        if self._ANSWER_RE.search(text):
            answer_attempt = 0.65
        if re.search(r"\b(i think|my answer|maybe the answer is|it should be)\b", text, re.IGNORECASE):
            answer_attempt = max(answer_attempt, 0.75)

        explanation = 0.8 if self._EXPLANATION_RE.search(text) else 0.0
        confusion = 0.85 if self._CONFUSION_RE.search(text) else 0.0
        misconception_clue = 0.85 if self._MISCONCEPTION_RE.search(text) else 0.0
        transfer_attempt = 0.8 if self._TRANSFER_RE.search(text) else 0.0
        topic_shift = 0.8 if self._TOPIC_SHIFT_RE.search(text) else 0.0
        self_correction = 0.85 if self._SELF_CORRECTION_RE.search(text) else 0.0
        curiosity = 0.8 if self._CURIOUSITY_RE.search(text) else 0.0

        return InputSignalScores(
            question=question,
            answer_attempt=answer_attempt,
            explanation=explanation,
            confusion=confusion,
            misconception_clue=misconception_clue,
            transfer_attempt=transfer_attempt,
            topic_shift=topic_shift,
            self_correction=self_correction,
            curiosity=curiosity,
        )

    def _merge_scores(self, heuristic: InputSignalScores, semantic: Mapping[str, float]) -> InputSignalScores:
        """Merge heuristic and semantic scores using a max rule.

        This prevents the semantic classifier from overriding a strong obvious
        cue (for example, a visible question mark).
        """
        def s(name: str, fallback: float) -> float:
            return max(fallback, float(semantic.get(name, 0.0)))

        return InputSignalScores(
            question=s("question", heuristic.question),
            answer_attempt=s("answer_attempt", heuristic.answer_attempt),
            explanation=s("explanation", heuristic.explanation),
            confusion=s("confusion", heuristic.confusion),
            misconception_clue=s("misconception_clue", heuristic.misconception_clue),
            transfer_attempt=s("transfer_attempt", heuristic.transfer_attempt),
            topic_shift=s("topic_shift", heuristic.topic_shift),
            self_correction=s("self_correction", heuristic.self_correction),
            curiosity=s("curiosity", heuristic.curiosity),
        )

    def _extract_candidate_concepts(
        self,
        text: str,
        *,
        session_context: Optional[Mapping[str, Any]] = None,
    ) -> List[str]:
        """Extract candidate concepts from the utterance and context.

        This is a lightweight prefilter. A dedicated concept resolver can do the
        final disambiguation later.
        """
        candidates: List[str] = []
        lexicon = list(self.config.concept_lexicon)

        # Add nearby concepts from the active session context, if available.
        if session_context:
            current = session_context.get("current_concept")
            if isinstance(current, str) and current:
                lexicon.append(current)

            recent = session_context.get("recent_concepts")
            if isinstance(recent, (list, tuple)):
                lexicon.extend([c for c in recent if isinstance(c, str)])

            chapter_terms = session_context.get("chapter_terms")
            if isinstance(chapter_terms, (list, tuple)):
                lexicon.extend([c for c in chapter_terms if isinstance(c, str)])

        lowered = text.lower()
        for concept in dict.fromkeys(lexicon):  # preserve order, remove duplicates
            normalized_concept = concept.lower().strip()
            if not normalized_concept:
                continue

            # Direct substring hit.
            if normalized_concept in lowered:
                candidates.append(concept)
                continue

            # Very small fuzzy rescue for obvious spelling noise.
            # This is intentionally light and should not replace semantic matching.
            if self._loose_match(normalized_concept, lowered):
                candidates.append(concept)

        return list(dict.fromkeys(candidates))

    def _loose_match(self, concept: str, text: str) -> bool:
        """Small lexical rescue for misspellings.

        Example: 'trignometry' should loosely match 'trigonometry'.
        """
        if len(concept) < 5:
            return False

        # Break the concept into small contentful pieces and see whether the
        # text contains most of them.
        concept_parts = [p for p in re.split(r"[_\-\s]+", concept) if p]
        if not concept_parts:
            return False

        hits = 0
        for part in concept_parts:
            if part in text:
                hits += 1
        return hits >= max(1, len(concept_parts) - 1)

    def _contains_formula(self, text: str) -> bool:
        """Detect whether the utterance contains a likely formula or expression."""
        if not text:
            return False
        formula_markers = ["=", "+", "-", "*", "/", "^", "∴", "∵"]
        return any(marker in text for marker in formula_markers) or bool(re.search(r"\b[a-zA-Z]\s*=\s*[^\s]", text))

    # -- the student-problem cue (§6.1; gates SOLVE_STUDENT_PROBLEM, audit A-2/D-1) --
    #
    # Deliberately NOT `_contains_formula`, which is far too loose to route on: it
    # fires on any '+' or '-' anywhere, so a hyphen in "well-known" would count as
    # an equation. This detector answers a narrower question — "did the student
    # bring an instance of their own that they want worked out?" — and it must be
    # deterministic, because the whole point of A-2 is that the routing decision
    # cannot depend on a model that scores a word problem as a transfer attempt.

    #: an '=' with a term on each side, at least one of which carries a digit or a
    #: lone variable letter — "x^2 - 5x + 6 = 0", "2y = 10". Prose containing '='
    #: is vanishingly rare in speech, but requiring real terms keeps it honest.
    _EQUATION_RE = re.compile(
        r"[0-9a-z\)\]]\s*(?:=|equals)\s*[-+]?\s*[0-9a-z\(\[]", re.IGNORECASE)

    #: an arithmetic operator sitting between two operands ("63/x", "2 * 4",
    #: "x^2"), which makes an expression even without an '='. At least one side
    #: must be a digit — otherwise "km/h" and "and/or" read as expressions.
    _EXPRESSION_RE = re.compile(
        r"(?:\d\s*[\^/*×÷]\s*[0-9a-z\(\[]|[0-9a-z\)\]]\s*[\^/*×÷]\s*\d)", re.IGNORECASE)

    #: imperative "work this out" verbs. `what is`/`how much` are included because
    #: that is how a child actually says it out loud.
    _SOLVE_VERB_RE = re.compile(
        r"\b(solve|calculate|compute|evaluate|simplify|factorise|factorize|"
        r"expand|prove|derive|work out|figure out|what is|what's|how much|how many|"
        r"find (?:the |out )?)\b", re.IGNORECASE)

    _DIGIT_RE = re.compile(r"\d")

    def detect_student_problem(self, text: str) -> Dict[str, Any]:
        """Is this utterance a problem instance the student wants solved?

        Returns ``{"is_problem": bool, "cue": str, "directive": bool}`` where
        ``cue`` names which rule fired, for the decision trace. Two ways to
        qualify:

        * **equation/expression** — the utterance carries maths of its own
          ("solve x^2 - 5x + 6 = 0"). Sufficient on its own.
        * **solve verb + numerals** — an imperative plus concrete numbers
          ("A train travels 63 km ... Find the speeds"). The numerals matter:
          "find the area of a circle" is a request to *teach* the concept, not
          to work an instance, and must keep routing to EXPLAIN.

        ``directive`` says the student ASKED US to do it (an imperative
        solve/find verb, or "what is …"). It exists to separate two utterances
        that both carry an equation: replying "x = 5" to our own diagnostic is
        an *answer attempt* and the grader owns it, whereas "solve 2x = 10" is a
        command aimed at the tutor and can never be an answer to a question we
        asked. Without the distinction a pending check swallows every problem
        the student brings while one is armed.
        """
        s = (text or "").strip()
        if not s:
            return {"is_problem": False, "cue": "", "directive": False}
        directive = bool(self._SOLVE_VERB_RE.search(s))
        if self._EQUATION_RE.search(s):
            return {"is_problem": True, "cue": "equation", "directive": directive}
        if self._EXPRESSION_RE.search(s):
            return {"is_problem": True, "cue": "expression", "directive": directive}
        if directive and self._DIGIT_RE.search(s):
            return {"is_problem": True, "cue": "solve_verb+numerals", "directive": True}
        return {"is_problem": False, "cue": "", "directive": False}


# -----------------------------------------------------------------------------
# Convenience helpers
# -----------------------------------------------------------------------------


def build_default_input_processor(concept_lexicon: Optional[Sequence[str]] = None) -> InputProcessor:
    """Factory for a default input processor instance."""
    config = InputProcessorConfig(concept_lexicon=list(concept_lexicon or []))
    return InputProcessor(config=config)


# -----------------------------------------------------------------------------
# Example usage
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    processor = build_default_input_processor(
        [
            "ohm_law",
            "current",
            "resistance",
            "linear_equation",
            "photosynthesis",
        ]
    )

    sample = "I think it is because resistance is high, but why does current reduce?"
    result = processor.process(
        sample,
        session_context={
            "current_concept": "ohm_law",
            "recent_concepts": ["current", "resistance"],
            "active_chapter": "Electric Current and Its Effects",
        },
    )

    print(result.to_dict())
