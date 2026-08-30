"""Personal Data — detection, redaction, and the type the sinks accept.

A sibling of ``perception/`` and ``child_safety/``, not a part of either:
independent prompt-of-record, schema, version string, context cache and eval.
``docs/architecture/PERSONAL_DATA_CONTRACT.md`` is normative.

**Not named ``privacy/``, deliberately** (§13): a module named ``privacy`` implies it
owns consent, retention and deletion, none of which it does, and over-claiming in a
package name is how an obligation comes to be assumed met.

Three facts about this package that are easy to get wrong:

1. **Personal data is off the safety axis entirely** (§1). Nothing here produces a
   ``SafetyClass``, sets ``safety_alert``, reaches the safeguarding queue on its own,
   or pauses the lesson. It is an annotation on an otherwise normal turn: detect,
   redact, keep teaching. The maths answer always ships first.

2. **There is no lexicon and no outage net** (§2). Unlike safety, where the regex
   survives as the degraded-mode net, a pattern detector here is not merely unnecessary
   but harmful: F1 = 0.379 on maths dialogue, failing by eating the maths. A Vertex
   outage therefore means **zero detection**, and what makes that safe is not detection
   at all — it is that ``redact`` returns ``None`` and the persisting sinks refuse to
   write a transcript without one.

3. **The verdict is identifier-bearing; ``TurnRedaction`` is not.** The verdict carries
   the child's actual phone number and is consumed by the redactor and dropped.
   ``TurnRedaction`` — placeholder text plus class labels — is the only thing that
   crosses a seam.

A deployment note that belongs here rather than in a runbook: **with no gateway wired
into the Turn Coordinator, every persisting sink writes its structured fields and no
transcript.** That is §8 behaving exactly as decided, not a bug — but it is also not a
silent state, and anyone who finds ``learning_log.jsonl`` rows with no ``question``
should look here first.
"""

from .contracts import (
    IdentifierClass,
    IdentifierFinding,
    PersonalDataContext,
    PersonalDataVerdict,
    VerdictStatus,
)
from .detector import PersonalDataDetector
from .dispatch import PersonalDataDispatch, PersonalDataGateway
from .prompt import (
    IDENTIFIER_CLASS_NAMES,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    prompt_hash,
)
from .redaction import (
    GenerationText,
    RedactedText,
    STAMP_INCOMPLETE,
    STAMP_NONE,
    STAMP_UNAVAILABLE,
    TurnRedaction,
    for_generation,
    placeholder,
    redact,
    turn_redaction,
)

__all__ = [
    "GenerationText",
    "IDENTIFIER_CLASS_NAMES",
    "IdentifierClass",
    "IdentifierFinding",
    "PROMPT_VERSION",
    "PersonalDataContext",
    "PersonalDataDetector",
    "PersonalDataDispatch",
    "PersonalDataGateway",
    "PersonalDataVerdict",
    "RedactedText",
    "SCHEMA_VERSION",
    "STAMP_INCOMPLETE",
    "STAMP_NONE",
    "STAMP_UNAVAILABLE",
    "TurnRedaction",
    "VerdictStatus",
    "for_generation",
    "placeholder",
    "prompt_hash",
    "redact",
    "turn_redaction",
]
