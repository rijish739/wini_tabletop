"""The child-safety response schema (Vertex controlled generation).

Kept apart from the detector so a schema change is a visible, versioned diff:
``SCHEMA_VERSION`` in ``prompt.py`` moves with this file, and that invalidates the
eval cache and the context cache and obliges a re-run of ``eval/safety_eval.py``
(§10.3).

What the schema does and does not buy (CLAUDE.md, Part 11): controlled generation
masks decoding to schema-valid tokens, so the model **cannot invent** a class name
outside the seven. It can still pick a **wrong-but-valid** one. That is why
``detector._validate`` exists downstream of this — the schema is the first belt,
not the only one.

Note the fields that are absent, and stay absent: ``severity`` (derived at one
site, §5) and ``caregiver_implicated`` (lexicon-only, §4.1). They are not optional
here; they are unrepresentable.
"""

from __future__ import annotations

from .prompt import SAFETY_CLASS_NAMES

#: Field names the belt reads. Kept as data so the test suite can assert the schema
#: and the validator never drift apart.
REQUIRED_FIELDS = (
    "axis_tripped",
    "classes",
    "imminence_cue",
    "named_means",
    "weapon",
    "arranged_meeting",
)

#: Fields the model must never be able to emit (§7.4). Asserted in the test suite
#: against both the schema and the validated verdict.
FORBIDDEN_FIELDS = ("severity", "caregiver_implicated", "tier", "priority")


def build_schema():
    """The ``google.genai`` response schema. Imported lazily — the offline lane must
    stay importable with no SDK installed."""
    from google.genai import types

    T = types.Type
    return types.Schema(
        type=T.OBJECT,
        properties={
            "axis_tripped": types.Schema(type=T.BOOLEAN),
            "classes": types.Schema(
                type=T.ARRAY,
                items=types.Schema(type=T.STRING, enum=list(SAFETY_CLASS_NAMES)),
            ),
            "imminence_cue": types.Schema(type=T.BOOLEAN),
            "named_means": types.Schema(type=T.BOOLEAN),
            "weapon": types.Schema(type=T.BOOLEAN),
            "arranged_meeting": types.Schema(type=T.BOOLEAN),
        },
        required=list(REQUIRED_FIELDS),
    )
