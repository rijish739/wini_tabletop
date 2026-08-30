"""The personal-data response schema (Vertex controlled generation).

Kept apart from the detector so a schema change is a visible, versioned diff:
``SCHEMA_VERSION`` in ``prompt.py`` moves with this file, and that invalidates the
eval cache and the context cache and obliges a re-run of both §12 corpora.

What the schema does and does not buy (CLAUDE.md, Part 11): controlled generation
masks decoding to schema-valid tokens, so the model **cannot invent** a class name
outside the nine. It can still pick a **wrong-but-valid** one, and — the failure that
actually matters here — it can still return a ``value`` that is not a substring of the
utterance. No schema can check that. ``detector._validate`` and ``redaction.redact``
are the belts downstream of this one.

Note the fields that are absent, and stay absent:

* ``start`` / ``end`` character offsets — §4 rejects spans outright;
* ``rewritten_text`` — §4 rejects a model rewrite outright;
* ``confidence`` / ``severity`` — §5: this system has no threshold anywhere, so a
  score would be a field with no consumer and an invitation to grow one.

They are not optional here; they are unrepresentable.
"""

from __future__ import annotations

from .prompt import IDENTIFIER_CLASS_NAMES

#: Field names the belt reads. Kept as data so the test suite can assert the schema
#: and the validator never drift apart.
REQUIRED_FIELDS = ("findings",)

#: Per-finding fields.
FINDING_FIELDS = ("identifier_class", "value")

#: Fields the model must never be able to emit. Asserted in the test suite against
#: both the schema and the validated verdict.
FORBIDDEN_FIELDS = (
    "start",
    "end",
    "span",
    "offset",
    "rewritten_text",
    "redacted_text",
    "confidence",
    "score",
    "severity",
)


def build_schema():
    """The ``google.genai`` response schema. Imported lazily — the offline lane must
    stay importable with no SDK installed."""
    from google.genai import types

    T = types.Type
    return types.Schema(
        type=T.OBJECT,
        properties={
            "findings": types.Schema(
                type=T.ARRAY,
                items=types.Schema(
                    type=T.OBJECT,
                    properties={
                        "identifier_class": types.Schema(
                            type=T.STRING, enum=list(IDENTIFIER_CLASS_NAMES)
                        ),
                        # No `enum`, no `pattern`: the value is free text by
                        # necessity — it is a verbatim copy of part of the child's
                        # utterance. Everything that constrains it is downstream.
                        "value": types.Schema(type=T.STRING),
                    },
                    required=list(FINDING_FIELDS),
                ),
            ),
        },
        required=list(REQUIRED_FIELDS),
    )
