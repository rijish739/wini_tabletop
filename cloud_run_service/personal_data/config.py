"""Personal-data detector configuration (PERSONAL_DATA_CONTRACT.md §13).

Its own env seam, deliberately NOT shared with perception's or child_safety's: this
call has its own prompt-of-record, schema, context cache and eval, and a flag flip
on either neighbour must never silently move the personal-data model.

Import-safe with no heavy deps.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# §13: "defaulting to gemini-2.5-flash@asia-south1, version pinned. Not flash-lite
# (measured slower, and a cross-border hop for children's data under DPDP)."
VERTEX_PERSONAL_DATA_MODEL = os.getenv(
    "VERTEX_PERSONAL_DATA_MODEL", "gemini-2.5-flash"
).strip()
VERTEX_PERSONAL_DATA_LOCATION = os.getenv(
    "VERTEX_PERSONAL_DATA_LOCATION", "asia-south1"
).strip()

# The default is EMPTY on purpose, for the same reason `child_safety` leaves its
# version empty: a version id is a fact about the Vertex catalog at deploy time, and
# inventing one here would put an unverified string into every eval record. Empty
# means *honestly unpinned*, is recorded as `model_pinned: false` everywhere, and is
# a hard block on the eval's release gate.
VERTEX_PERSONAL_DATA_MODEL_VERSION = os.getenv(
    "VERTEX_PERSONAL_DATA_MODEL_VERSION", ""
).strip()


def resolved_model() -> str:
    """The model id actually sent to Vertex — pinned when a version is configured."""
    if VERTEX_PERSONAL_DATA_MODEL_VERSION:
        return f"{VERTEX_PERSONAL_DATA_MODEL}@{VERTEX_PERSONAL_DATA_MODEL_VERSION}"
    return VERTEX_PERSONAL_DATA_MODEL


def model_pinned() -> bool:
    return bool(VERTEX_PERSONAL_DATA_MODEL_VERSION)


# §13: 5s hard wall-clock for the whole call INCLUDING its one retry. Never an
# SDK-level timeout (CLAUDE.md gotcha: those have stalled for hours).
PERSONAL_DATA_TIMEOUT_S = float(os.getenv("PERSONAL_DATA_TIMEOUT_S", "5"))

# The floor a retry needs to be worth attempting. Below this the remaining envelope
# cannot fit a round-trip, and the retry is skipped rather than started-and-abandoned.
PERSONAL_DATA_RETRY_MIN_S = float(os.getenv("PERSONAL_DATA_RETRY_MIN_S", "0.75"))

# Optional Vertex context-cache resource name for the static block (§13).
PERSONAL_DATA_CACHED_CONTENT = (
    os.getenv("PERSONAL_DATA_CACHED_CONTENT", "").strip() or None
)

# How many utterances the per-process verdict memo holds. Memoized on utterance_id,
# never on text: two children saying the same words must not share a verdict, and a
# replayed turn must not re-bill.
PERSONAL_DATA_MEMO_SIZE = int(os.getenv("PERSONAL_DATA_MEMO_SIZE", "256"))

# Where build_personal_data.py writes the prompt-of-record and its hash.
BUILD_DIR = Path(__file__).resolve().parent / "build"


# ---------------------------------------------------------------------------
# The production wiring switch
# ---------------------------------------------------------------------------
# Whether `runtime.compatibility.TutorLoopCompatibilityFacade` builds a gateway and
# hands it to the Turn Coordinator. **Default OFF, and that is a test-safety decision,
# not a doubt about the contract.**
#
# The facade is the one production construction site AND is exercised directly by the
# offline test suite. A default of ON would mean that a developer with working ADC on
# their machine bills a Vertex call for every turn in `python -m pytest` — a test suite
# that spends money is a test suite people stop running. `child_safety` avoids the same
# trap by not wiring its gateway in the facade at all.
#
# What OFF actually means, stated plainly because it is not nothing: no detector runs,
# so every persisting sink writes its structured fields and `[WITHHELD_NO_REDACTION]`
# in place of the transcript. That is §8 behaving exactly as decided — it is the
# correct shape of "zero detection" — but a `learning_log.jsonl` full of withheld
# transcripts is a deployment fact, not a bug, and this flag is where it is decided.
#
# Set PERSONAL_DATA_ENABLED=1 in the Cloud Run environment.
PERSONAL_DATA_ENABLED = os.getenv(
    "PERSONAL_DATA_ENABLED", "0"
).strip().lower() not in ("0", "false", "no", "")
