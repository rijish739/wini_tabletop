"""Perception-layer configuration flags (Part 11).

Central place for every env flag the front door reads, so tutor_loop.py and
gemini_perception.py agree on names and defaults (PART11_GEMINI_PERCEPTION_LAYER.md
§11). Import-safe with no heavy deps.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Perception is Gemini: one structured call (GeminiPerception). Promoted Stage 4
# (2026-07-02: concept 0.930/0.990 with the §5.5 hardening + resolver cross-check,
# behavioral signal eval PASS, intent 1.0, safety gate 1.0 — see
# eval/perception_eval_report.md + eval/behavioral_eval_report.md); the MiniLM-heads
# runtime path was RETIRED at Stage 6 (2026-07-02). The flag is kept only so a stale
# env value degrades to a warning in tutor_loop instead of a crash; head artifacts
# stay on disk as the eval baseline (eval/*_eval.py load them directly).
PERCEPTION_BACKEND = os.getenv("PERCEPTION_BACKEND", "gemini").strip().lower()

# Stage 1 shadow flag — RETIRED with the heads at Stage 6 (2026-07-02); kept for
# .env backward-compat only, read by nothing.
PERCEPTION_SHADOW = os.getenv("PERCEPTION_SHADOW", "false").strip().lower() in {"1", "true", "yes", "on"}

VERTEX_REGION = os.getenv("VERTEX_REGION", "asia-south1")
VERTEX_PERCEPTION_MODEL = os.getenv("VERTEX_PERCEPTION_MODEL", "gemini-2.5-flash")
# Hard wall-clock timeout on the perception call (CLAUDE.md: never trust SDK
# timeouts). Perception is a small structured reply, so this is tighter than the
# generation timeout.
PERCEPTION_TIMEOUT_S = float(os.getenv("PERCEPTION_TIMEOUT_S", "12"))

# Optional Vertex context-cache resource name for the static block (Stage 5).
PERCEPTION_CACHED_CONTENT = os.getenv("PERCEPTION_CACHED_CONTENT", "").strip() or None

# §5.5 concept hardening: number of MiniLM-similar concepts passed to Gemini as
# `candidate_concepts` hints in the per-turn prompt (0 disables the hint). Uses the
# resolver's shipped anchor_embeddings.npy + concepts_meta.json; hints only — the
# schema still allows any catalog id, and INHERIT stays the abstain sentinel.
PERCEPTION_CANDIDATE_K = int(os.getenv("PERCEPTION_CANDIDATE_K", "8"))

# §5.5 hybrid cross-check: when Gemini picks a catalog concept, the local MiniLM
# resolver re-ranks it — if the resolver's confident (>= its tau) top-1 is inside
# Gemini's {primary + secondaries} set, it is promoted to primary (Gemini's pick
# drops into the secondaries). Deterministic post-processing, measured on the frozen
# TEST cache: top-1 0.890 -> 0.930, top-3 0.990 (2026-07-02).
PERCEPTION_CONCEPT_CROSSCHECK = os.getenv(
    "PERCEPTION_CONCEPT_CROSSCHECK", "true").strip().lower() in {"1", "true", "yes", "on"}

# Score >= this becomes a fired `signal` in the signals list handed to
# derive_state_deltas. The continuous scores still feed derive_cognitive_update
# unchanged; this only affects the discrete signals list. Recalibrated on the
# frozen TEST split at Stage 2 (§5.5b) — 0.5 is the pre-calibration operating point.
PERCEPTION_SIGNAL_THRESHOLD = float(os.getenv("PERCEPTION_SIGNAL_THRESHOLD", "0.5"))

# Where build_perception.py writes the generated schema enums + cached block.
BUILD_DIR = Path(__file__).resolve().parent / "build"
