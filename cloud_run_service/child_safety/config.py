"""Child-safety detector configuration (SAFETY_ROUTE_TAXONOMY.md §7.2).

Its own env seam, mirroring ``llm_vertex.VERTEX_SMALL_MODEL`` /
``VERTEX_SMALL_LOCATION`` and deliberately NOT sharing perception's flags: the
safety call has its own prompt-of-record, schema, context cache and eval, and a
perception flag flip must never silently move the safety model.

Import-safe with no heavy deps.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# §7.2: do NOT default to gemini-2.5-flash-lite. MEASURED 2026-07-25
# (llm_vertex.py:29-36): flash-lite is available only in `global` / `us-central1`,
# not asia-south1, and is SLOWER than gemini-2.5-flash@asia-south1 on short
# schema-constrained calls. It would also move children's disclosures out of India,
# which the DPDP anchor makes a residency decision, not a performance one.
VERTEX_SAFETY_MODEL = os.getenv("VERTEX_SAFETY_MODEL", "gemini-2.5-flash").strip()
VERTEX_SAFETY_LOCATION = os.getenv("VERTEX_SAFETY_LOCATION", "asia-south1").strip()

# §7.2: "Pin the model version explicitly rather than riding a floating alias, so a
# Google-side rollout cannot change child-safety behavior between two deploys of
# identical code."
#
# The default is EMPTY on purpose. A version id is a fact about the Vertex catalog
# at deploy time; inventing one here would put an unverified string into every case
# record. Empty therefore means *honestly unpinned*, which is:
#   - recorded in every case record as `model_pinned: false`;
#   - recorded in every eval record;
#   - a HARD BLOCK on the cutover gate (eval/safety_eval.py --cutover), which is the
#     only place the distinction is allowed to matter for a release decision.
# Set VERTEX_SAFETY_MODEL_VERSION to the concrete version before cutover.
VERTEX_SAFETY_MODEL_VERSION = os.getenv("VERTEX_SAFETY_MODEL_VERSION", "").strip()


def resolved_model() -> str:
    """The model id actually sent to Vertex — pinned when a version is configured."""
    if VERTEX_SAFETY_MODEL_VERSION:
        return f"{VERTEX_SAFETY_MODEL}@{VERTEX_SAFETY_MODEL_VERSION}"
    return VERTEX_SAFETY_MODEL


def model_pinned() -> bool:
    return bool(VERTEX_SAFETY_MODEL_VERSION)


# §7.3: hard wall-clock envelope for the whole call INCLUDING its one retry.
# Never an SDK-level timeout (CLAUDE.md gotcha: those have stalled for hours).
SAFETY_TIMEOUT_S = float(os.getenv("SAFETY_TIMEOUT_S", "5"))

# The floor a retry needs to be worth attempting. Below this the remaining envelope
# cannot fit a round-trip and the retry is skipped rather than started-and-abandoned.
SAFETY_RETRY_MIN_S = float(os.getenv("SAFETY_RETRY_MIN_S", "0.75"))

# Optional Vertex context-cache resource name for the static block (§7.1).
SAFETY_CACHED_CONTENT = os.getenv("SAFETY_CACHED_CONTENT", "").strip() or None

# How many utterances the per-process verdict memo holds. Memoized on utterance_id
# (§7.1), never on text, so a replayed turn does not re-bill.
SAFETY_MEMO_SIZE = int(os.getenv("SAFETY_MEMO_SIZE", "256"))

# Where build_safety.py writes the prompt-of-record and its hash.
BUILD_DIR = Path(__file__).resolve().parent / "build"
