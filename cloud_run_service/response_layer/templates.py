"""Template-first planning tables (§5.2 Planning Modes, §18.1 Fast Path, review A1/B8).

Two things live here, shared by BOTH the planner (to build a spine) and the validator
(to check the spine is a legal decomposition of the upstream action, §B8 boundary):

    ALLOWED_STEPS   pedagogical_action -> the set of legal ``pedagogical_step`` slugs
    SPINES          pedagogical_action -> an ordered list of BeatTemplate

The macro ``pedagogical_action`` is owned UPSTREAM by the Pedagogical Decision Engine
(tutor_loop.rules_decide). The Response Layer only choreographs it into beats — it may
never pick a different macro action (§3.8). The allowed-step table is how the validator
enforces that: every beat's step must be legal under the turn's action.

Why template-first: it produces the beat spine (structure + which beat is a visual
candidate + where an assessment hook sits) with ZERO model latency, protecting the
TTFA <= 4 s budget (§18.0). The spoken words are still filled by the existing streamed
generator (planner.py fills nothing itself in this Phase-1+2 slice), so streaming and
Part-13 latency are untouched.

Note on ``STEP_CORRECT``: it is a known step but appears in NO spine — a misconception
correction is a FUTURE turn after the probe confirms (probe-before-correct, §A3). Keeping
it known lets the validator reject any (future LLM-authored) beat that tries to correct an
unconfirmed misconception.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import AssessmentHookType, ExecutionMode, RobotPrimitive

# --- pedagogical step vocabulary (slugs) -----------------------------------------
STEP_ORIENT = "orient"                       # brief framing / activate prior
STEP_EXPLAIN = "explain"                     # the core explanation
STEP_DEFINE = "define"
STEP_REPRESENTATION_TRANSLATION = "representation_translation"
STEP_WORKED_STEP = "worked_step"
STEP_SOLVE_INSTANCE = "solve_instance"       # solve the student's own problem
STEP_POSE_PROBLEM = "pose_problem"           # give a problem to attempt
STEP_PROBE = "probe"                         # diagnostic / misconception probe
STEP_CORRECT = "correct"                     # misconception correction (gated; no spine)
STEP_REFLECT = "reflect"
STEP_ENCOURAGE = "encourage"
STEP_WHY_IT_MATTERS = "why_it_matters"
STEP_EXAMPLE = "example"
STEP_CHALLENGE = "challenge"                 # socratic
STEP_CHECK = "check"                         # micro check for understanding
STEP_TEST_QUESTION = "test_question"
STEP_TEST_SUMMARY = "test_summary"
STEP_CLOSE = "close"

# steps that are inherently visual candidates (the gate still decides yes/no, §12.1)
_VISUAL_STEPS = frozenset({
    STEP_EXPLAIN, STEP_REPRESENTATION_TRANSLATION, STEP_WORKED_STEP,
    STEP_SOLVE_INSTANCE, STEP_EXAMPLE, STEP_WHY_IT_MATTERS,
})


@dataclass
class BeatTemplate:
    """One slot in a spine. The planner instantiates it into a concrete ``Beat``."""

    step: str
    visual_candidate: bool = False               # run the Visual Benefit Gate here
    assessment: AssessmentHookType | None = None
    assessment_mode: ExecutionMode = ExecutionMode.LOCAL
    claim_hint: str = ""                         # seeds atomic_learning_claim
    robot: list[RobotPrimitive] = field(default_factory=list)


# --- the spines (kept small; the streamed generator fills the words) --------------
# Each spine's *first* visual_candidate beat is where the display decision is made.
# Assessment hooks are carried in-schema; their runtime (grading/branching) is Phase 4/5.
SPINES: dict[str, list[BeatTemplate]] = {
    "EXPLAIN": [
        BeatTemplate(STEP_EXPLAIN, visual_candidate=True,
                     claim_hint="Explain the concept in one clear idea.",
                     robot=[RobotPrimitive.LOOK_AT_SCREEN]),
        BeatTemplate(STEP_CHECK, assessment=AssessmentHookType.MICRO_CHECK,
                     assessment_mode=ExecutionMode.SPOKEN,
                     claim_hint="Check the learner followed the idea.",
                     robot=[RobotPrimitive.LOOK_AT_LEARNER]),
    ],
    "REPRESENTATION_TRANSLATION": [
        BeatTemplate(STEP_REPRESENTATION_TRANSLATION, visual_candidate=True,
                     claim_hint="Show the same idea in a representation the learner can picture.",
                     robot=[RobotPrimitive.POINT_TO_SCREEN_REGION]),
        BeatTemplate(STEP_CHECK, assessment=AssessmentHookType.REPRESENTATION_TRANSLATION_CHECK,
                     assessment_mode=ExecutionMode.SPOKEN,
                     claim_hint="Check the learner can read the new representation."),
    ],
    "VISUAL_ANALOGY": [
        BeatTemplate(STEP_REPRESENTATION_TRANSLATION, visual_candidate=True,
                     claim_hint="Give a concrete visual analogy for the concept."),
    ],
    "WORKED_EXAMPLE": [
        BeatTemplate(STEP_WORKED_STEP, visual_candidate=True,
                     claim_hint="Work one example through every step."),
        BeatTemplate(STEP_CHECK, assessment=AssessmentHookType.WORKED_STEP_CHECK,
                     assessment_mode=ExecutionMode.SPOKEN,
                     claim_hint="Check the learner can do the next step."),
    ],
    "COMPLETION_STEP": [
        BeatTemplate(STEP_WORKED_STEP, visual_candidate=True,
                     claim_hint="Work every step except the last."),
        BeatTemplate(STEP_CHECK, assessment=AssessmentHookType.WORKED_STEP_CHECK,
                     assessment_mode=ExecutionMode.SPOKEN,
                     claim_hint="Ask the learner to do only the final step."),
    ],
    "SOLVE_STUDENT_PROBLEM": [
        BeatTemplate(STEP_SOLVE_INSTANCE, visual_candidate=True,
                     claim_hint="Solve the learner's own problem with the stored method."),
    ],
    "ANALOGOUS_EXAMPLE": [
        BeatTemplate(STEP_EXAMPLE, visual_candidate=True,
                     claim_hint="Give one analogous worked example."),
    ],
    "WHY_IT_MATTERS": [
        BeatTemplate(STEP_WHY_IT_MATTERS, visual_candidate=False,
                     claim_hint="Answer why this is worth learning; do not deflect."),
    ],
    "MISCONCEPTION_PROBE": [
        # A probe turn only ARMS the probe (§A3). No correction step here — that is a
        # later turn after the result confirms. Spoken execution (cloud checkpoint).
        BeatTemplate(STEP_PROBE, assessment=AssessmentHookType.MISCONCEPTION_PROBE,
                     assessment_mode=ExecutionMode.SPOKEN,
                     claim_hint="Ask the diagnostic question; do not reveal the correction.",
                     robot=[RobotPrimitive.LOOK_AT_LEARNER]),
    ],
    "SOCRATIC_Q": [
        BeatTemplate(STEP_CHALLENGE, assessment=AssessmentHookType.DIAGNOSTIC_PROBE,
                     assessment_mode=ExecutionMode.SPOKEN,
                     claim_hint="Pose one guiding question; do not lecture.",
                     robot=[RobotPrimitive.LOOK_AT_LEARNER]),
    ],
    "QUIZ": [
        BeatTemplate(STEP_POSE_PROBLEM, assessment=AssessmentHookType.MICRO_CHECK,
                     assessment_mode=ExecutionMode.SPOKEN,
                     claim_hint="Pose one problem in the learner's ZPD."),
    ],
    "ISOMORPHIC_PRACTICE": [
        BeatTemplate(STEP_POSE_PROBLEM, assessment=AssessmentHookType.MICRO_CHECK,
                     assessment_mode=ExecutionMode.SPOKEN,
                     claim_hint="Pose one fresh problem of the same type."),
    ],
    "TRANSFER_PROBLEM": [
        BeatTemplate(STEP_POSE_PROBLEM, assessment=AssessmentHookType.DIAGNOSTIC_PROBE,
                     assessment_mode=ExecutionMode.SPOKEN,
                     claim_hint="Pose one near-transfer problem."),
    ],
    "METACOGNITIVE_REFLECT": [
        BeatTemplate(STEP_REFLECT, assessment=AssessmentHookType.REFLECTION_PROMPT,
                     assessment_mode=ExecutionMode.SPOKEN,
                     claim_hint="Ask the learner to explain it back, or offer the next step."),
    ],
    "ENCOURAGE": [
        BeatTemplate(STEP_ENCOURAGE, visual_candidate=False,
                     claim_hint="Acknowledge effort warmly, then one simple next idea.",
                     robot=[RobotPrimitive.ENCOURAGE]),
    ],
    "TEST_QUESTION": [
        # A test question is delivered verbatim (no visual — test integrity §12.1).
        BeatTemplate(STEP_TEST_QUESTION, assessment=AssessmentHookType.MICRO_CHECK,
                     assessment_mode=ExecutionMode.SPOKEN,
                     claim_hint="Deliver the exact test question."),
    ],
    "TEST_SUMMARY": [
        BeatTemplate(STEP_TEST_SUMMARY, visual_candidate=False,
                     claim_hint="Report the test result."),
    ],
}

#: Fallback spine for any action without a template — a single explain beat, which is
#: exactly today's behaviour (one answer, gate may still earn a visual).
DEFAULT_SPINE: list[BeatTemplate] = [
    BeatTemplate(STEP_EXPLAIN, visual_candidate=True,
                 claim_hint="Explain the concept in one clear idea.",
                 robot=[RobotPrimitive.LOOK_AT_SCREEN]),
]


def _steps_of(spine: list[BeatTemplate]) -> set[str]:
    return {bt.step for bt in spine}


#: allowed-step table (§B8). Derived from the spines plus a few steps a future LLM
#: planner may legitimately add (orient/close are always legal framing; the visual
#: actions may also define/explain). STEP_CORRECT is legal ONLY for a confirmed-
#: misconception correction turn, which the validator gates separately.
ALLOWED_STEPS: dict[str, set[str]] = {
    action: _steps_of(spine) | {STEP_ORIENT, STEP_CLOSE}
    for action, spine in SPINES.items()
}
# widen a few actions with obviously-legal adjacent steps
ALLOWED_STEPS["EXPLAIN"] |= {STEP_DEFINE, STEP_EXAMPLE, STEP_REFLECT}
ALLOWED_STEPS["REPRESENTATION_TRANSLATION"] |= {STEP_EXPLAIN}
ALLOWED_STEPS["WORKED_EXAMPLE"] |= {STEP_EXPLAIN}
ALLOWED_STEPS["SOLVE_STUDENT_PROBLEM"] |= {STEP_WORKED_STEP}
ALLOWED_STEPS["ENCOURAGE"] |= {STEP_EXPLAIN}
ALLOWED_STEPS["WHY_IT_MATTERS"] |= {STEP_EXPLAIN}


def spine_for(action: str | None) -> list[BeatTemplate]:
    """The template spine for an upstream action, or the default single-explain spine."""
    if action and action in SPINES:
        return SPINES[action]
    return DEFAULT_SPINE


def is_step_allowed(action: str | None, step: str) -> bool:
    """True if ``step`` is a legal decomposition of ``action`` (§B8). Unknown actions
    fall back to the default-spine step set so the fallback path always validates."""
    if not action or action not in ALLOWED_STEPS:
        return step in (_steps_of(DEFAULT_SPINE) | {STEP_ORIENT, STEP_CLOSE})
    return step in ALLOWED_STEPS[action]


def visual_candidate_action(action: str | None) -> bool:
    """True if this action's spine has any visual-candidate beat (a quick pre-check)."""
    return any(bt.visual_candidate for bt in spine_for(action))
