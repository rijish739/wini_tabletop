# Cues and Signals in the Wini Architecture

This document catalogs all the cues and signals used in the `utterance_intake`, `interaction_control`, and `perception` layers, detailing whether their detection mechanisms are regex-based, model-based, or LLM-based.

## 1. Intake Layer (`cloud_run_service/utterance_intake/`)

The Intake layer is deterministic and model-free (or relies on external models like STT). It produces frozen observations.

*   **SafetySignals** (`SafetyClass`: `SELF_HARM`, `HARM_BY_OTHER`, etc.):
    *   **Mechanism**: Regex-based (Lexicon only). It acts as the degraded-mode outage net.
    *   **Source**: [utterance_intake/observation.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/utterance_intake/observation.py#L65-L89), [utterance_intake/intake.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/utterance_intake/intake.py#L227)
*   **LegibilityCue** (`LEGIBLE`, `EMPTY`, `NO_ALPHANUMERIC`, `CHARACTER_RUN`, `NO_LEXICAL_CONTENT`, `KEYBOARD_MASH`):
    *   **Mechanism**: Regex-based / Heuristic.
    *   **Source**: [utterance_intake/observation.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/utterance_intake/observation.py#L95-L101)
*   **TranscriptReading / DoubtCause** (`UTTERANCE_CONFIDENCE`, `WORD_CONFIDENCE`, `ALTERNATE_DISAGREEMENT`, `AMBIGUOUS_PARSE`, `OUT_OF_GRAMMAR`):
    *   **Mechanism**: Model-based (confidence floats from STT) + Grammar/Heuristics.
    *   **Source**: [utterance_intake/observation.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/utterance_intake/observation.py#L125-L131)
*   **ProblemCue** (`EQUATION`, `EXPRESSION`, `SOLVE_VERB_NUMERALS`):
    *   **Mechanism**: Regex-based.
    *   **Source**: [utterance_intake/observation.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/utterance_intake/observation.py#L186-L190)
*   **ReferenceReading / AnaphorSpan**:
    *   **Mechanism**: Regex-based (matching "this", "that", "it", etc.).
    *   **Source**: [utterance_intake/intake.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/utterance_intake/intake.py) (`_ANAPHOR_RE`)

## 2. Perception Layer (`cloud_run_service/perception/`)

The Perception layer centralizes LLM and deterministic fallback capabilities.

*   **Intents** (`LEARNING`, `SOCIAL`, `META_CAPABILITY`, `OFF_DOMAIN_ACADEMIC`, `SESSION_CONTROL`, `EMOTIONAL`, `SAFETY`, `NONSENSE`):
    *   **Mechanism**: LLM-based (Gemini single call). `SOCIAL` and `META_CAPABILITY` are prime examples of non-learning intents.
    *   **Source**: [perception/route.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/perception/route.py#L14-L24), [perception/gemini_perception.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/perception/gemini_perception.py#L388)
*   **answer_attempt**:
    *   **Mechanism**: LLM-based (Gemini boolean flag). Identifies if the user is answering a pending question.
    *   **Source**: [perception/gemini_perception.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/perception/gemini_perception.py#L428)
*   **also_learning**:
    *   **Mechanism**: LLM-based (Gemini boolean flag). Identifies non-LEARNING turns that carry a math question.
    *   **Source**: [perception/gemini_perception.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/perception/gemini_perception.py#L423)
*   **concept_id & secondary_concepts**:
    *   **Mechanism**: LLM-based cross-checked with Model-based (MiniLM similarity).
    *   **Source**: [perception/gemini_perception.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/perception/gemini_perception.py#L495)
*   **signal_scores** (Pedagogical Labels):
    *   **Mechanism**: LLM-based (Gemini classification into 38 labels).
    *   **Source**: [perception/gemini_perception.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/perception/gemini_perception.py#L446)
*   **session_control_mode** (`STOP`, `TEST`, `PRACTICE`, `EXPLAIN`):
    *   **Mechanism**: LLM-based (Gemini classification when intent is `SESSION_CONTROL`).
    *   **Source**: [perception/gemini_perception.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/perception/gemini_perception.py#L407)
*   **topic_phrasing**:
    *   **Mechanism**: LLM-based (Gemini extraction of raw topic phrasing).
    *   **Source**: [perception/gemini_perception.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/perception/gemini_perception.py#L415)
*   **SAFETY Gate** (Outage Net / Fallback):
    *   **Mechanism**: Regex-based (`is_safety`). Used only if the model is unavailable or down.
    *   **Source**: [perception/gates.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/perception/gates.py#L103)
*   **NONSENSE Gate** (Fallback):
    *   **Mechanism**: Regex-based / Heuristic (`is_nonsense`).
    *   **Source**: [perception/gates.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/perception/gates.py#L120)

## 3. Input / Interaction Control Layer (`cloud_run_service/interaction_control/`)

This layer governs the interaction states by leveraging downstream cues.

*   **`_consume_pending_shift`**:
    *   **Mechanism**: Regex-based (looks for confirm/deny words like yes/no) + State-based (checks `pending_shift`).
    *   **Source**: [interaction_control/control.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/interaction_control/control.py#L851)
*   **`_consume_pending_mode_control`**:
    *   **Mechanism**: State-based logic evaluating session capability transitions.
    *   **Source**: [interaction_control/control.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/interaction_control/control.py#L580)
*   **`_maybe_topic_shift`**:
    *   **Mechanism**: LLM-based (`mode_cue` via `session_control_mode`) + Model-based (`topic_candidates` via MiniLM embeddings).
    *   **Source**: [interaction_control/control.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/interaction_control/control.py#L676)
*   **`_maybe_decline_topic`**:
    *   **Mechanism**: Regex-based (`wants_different_topic`), LLM-based (`mode_cue`), and Model-based (`topic_candidates`).
    *   **Source**: [interaction_control/control.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/interaction_control/control.py#L624)
*   **`_maybe_stop_mode`**:
    *   **Mechanism**: LLM-based (`mode_cue` returning "STOP").
    *   **Source**: [interaction_control/control.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/interaction_control/control.py#L825)

## 4. Notable Runtime Logic (e.g., `cloud_run_service/tutor_loop.py`)

Though officially outside the strict three folders, these are crucial aggregations of the layer cues above:

*   **`non_attempt`**:
    *   **Mechanism**: Complex heuristic combining LLM-based cues (e.g., `answer_attempt` is false, existence of `acknowledgment`, `clarification`, `question`, `fresh_request` signals) AND Regex-based cues (`student_problem` with `directive`).
    *   **Source**: [tutor_loop.py](file:///d:/AI_tutor/wini_tabletop/cloud_run_service/tutor_loop.py#L2305)

## Additional Dependencies (`cloud_run_service/cognitive_classifier/cues.py`)

A few signals remain available as deterministic offline regexes but are imported for runtime logic:
*   **`wants_different_topic`** (`DIFFERENT_TOPIC_RE`): Regex-based.
*   *Note: Many other regex cues (`is_clarification_request`, `is_question`, etc.) have been retired from the active feature vector as part of the perception LLM migration.*

## 5. Complete List of Perception Intents and Cognitive Signals

The following 8 intents and 42 cognitive signals are generated by the LLM-based perception layer:

### 8 Intents
1. `LEARNING`
2. `SOCIAL`
3. `META_CAPABILITY`
4. `OFF_DOMAIN_ACADEMIC`
5. `SESSION_CONTROL`
6. `EMOTIONAL`
7. `SAFETY`
8. `NONSENSE`

### 42 Cognitive Signals
1. `abstraction_attempt`
2. `acknowledgment`
3. `algebraic`
4. `answer_attempt`
5. `anxiety`
6. `cognitive_overload`
7. `conflict`
8. `confusion`
9. `curiosity`
10. `diagrammatic`
11. `disengagement`
12. `environmental_feedback`
13. `example_request`
14. `frustration`
15. `graphical`
16. `high_confidence`
17. `hint_dependency`
18. `low_confidence`
19. `misconception_clue`
20. `physical`
21. `prerequisite_awareness`
22. `prerequisite_weakness`
23. `procedural_focus`
24. `question`
25. `ready_for_next`
26. `recurring_error`
27. `representation_shift`
28. `request_hint`
29. `request_representation`
30. `self_correction`
31. `self_monitoring`
32. `shortcut_seeking`
33. `simplification_request`
34. `skepticism`
35. `tabular`
36. `topic_shift`
37. `transfer_attempt`
38. `verbal_analogy`
39. `animation_request`
40. `learning_request`
41. `purpose_question`
42. `real_life_request`
