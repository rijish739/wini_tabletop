"""Parent-friendly progress report built from the learner state + store metadata.

Read-only summarizer for the parent dashboard: joins learner_state.json against
rag_store/concepts.json (human concept names), rag_store/graph.json (misconception
text / correct idea / owning concept), rag_store/learning_log.jsonl (recent
activity) and rag_store/safety_alerts.jsonl — and translates every internal id,
flag and score into plain-English fields a parent can read.

Consumed by wini_server.py (GET /progress) on the device/cloud side and by
parent_dashboard.py --local on the laptop. Pure stdlib, no model imports, safe
to call while the brain is still loading.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
COLD_START_MASTERY = 0.30  # mirrors learner_state.COLD_START_MASTERY (no heavy import)

CHAPTER_NAMES = {
    "jemh101": "Real Numbers",
    "jemh102": "Polynomials",
    "jemh103": "Pair of Linear Equations",
    "jemh104": "Quadratic Equations",
    "jemh105": "Arithmetic Progressions",
    "jemh106": "Triangles",
    "jemh107": "Coordinate Geometry",
    "jemh108": "Introduction to Trigonometry",
    "jemh109": "Applications of Trigonometry",
    "jemh110": "Circles",
    "jemh111": "Areas Related to Circles",
    "jemh112": "Surface Areas and Volumes",
    "jemh113": "Statistics",
    "jemh114": "Probability",
    "jemh1a1": "Proofs in Mathematics",
    "jemh1a2": "Mathematical Modelling",
}

def _live_flags(cs: dict) -> list:
    """Per-concept flags still inside their decay window (audit A-6).

    Flags carry a `flag_seen` timestamp since 2026-07-23. Anything older than
    FLAG_TTL_DAYS is a past moment, not a present condition, and must not be
    reported to a parent as current. Undated flags are legacy rows written
    before timestamping; they fall back to `last_practiced`, and if even that is
    missing they are shown (an undated flag is not evidence of staleness).
    """
    from cognitive_analyzer.analyzer import FLAG_TTL_DAYS

    seen = cs.get("flag_seen") or {}
    now = datetime.now(timezone.utc)
    out = []
    for f in (cs.get("flags") or []):
        stamp = seen.get(f) or cs.get("last_practiced")
        if not stamp:
            out.append(f)
            continue
        try:
            ts = datetime.fromisoformat(stamp)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            out.append(f)
            continue
        if (now - ts).days <= FLAG_TTL_DAYS:
            out.append(f)
    return out


FLAG_LABELS = {
    "transfer_ready_evidence": {"label": "Ready for tougher challenges", "tone": "good"},
    "self_corrected": {"label": "Corrected their own mistake", "tone": "good"},
    "hint_requested": {"label": "Asked for hints here", "tone": "neutral"},
    "misconception_suspected": {"label": "Wini spotted a possible mix-up", "tone": "warn"},
    "prerequisite_weakness_clue": {"label": "May need to brush up the basics", "tone": "warn"},
    "frustration_risk": {"label": "Showed some frustration", "tone": "warn"},
}

MISCONCEPTION_STATUS = {
    "active": {"label": "Working through it", "tone": "warn"},
    "recurring": {"label": "It came back — practicing again", "tone": "warn"},
    "weakening": {"label": "Almost cleared", "tone": "neutral"},
    "resolved": {"label": "Cleared", "tone": "good"},
}

THINKING_SKILLS = {
    "KI": {"label": "Connecting ideas",
           "help": "How well ideas from different topics link together."},
    "KT": {"label": "Applying to new problems",
           "help": "Using what was learned on problems never seen before."},
    "CT": {"label": "Critical thinking",
           "help": "Reasoning about why something works, not just how."},
}

# Part 12 (§4.2): the per-concept mastery-gate state, in parent-friendly words.
GATE_LABELS = {
    "passed": {"label": "Passed the check", "tone": "good"},
    "failed_pending_retest": {"label": "Practising for a re-check", "tone": "warn"},
    "none": {"label": "Not checked yet", "tone": "neutral"},
}

# ---------------------------------------------------------------------------
# Store metadata (static — loaded once per process)
# ---------------------------------------------------------------------------
_META: Optional[Dict[str, Any]] = None


def _load_meta(root: Path) -> Dict[str, Any]:
    global _META
    if _META is not None:
        return _META
    concepts: Dict[str, Dict[str, str]] = {}
    try:
        for c in json.loads((root / "rag_store" / "concepts.json").read_text(encoding="utf-8")):
            concepts[c["concept_id"]] = {
                "name": c.get("name") or _titleize(c["concept_id"]),
                "chapter": CHAPTER_NAMES.get(c.get("chapter_doc", ""), ""),
            }
    except Exception:
        pass
    mis_nodes: Dict[str, Dict[str, Any]] = {}
    mis_owner: Dict[str, str] = {}
    try:
        g = json.loads((root / "rag_store" / "graph.json").read_text(encoding="utf-8"))
        for n in g.get("nodes", []):
            if n.get("type") == "misconception":
                mis_nodes[n.get("id", "")] = n
        for e in g.get("edges", []):
            if e.get("relation") == "has_misconception":
                mis_owner[e.get("target", "")] = e.get("source", "")
    except Exception:
        pass
    _META = {"concepts": concepts, "mis_nodes": mis_nodes, "mis_owner": mis_owner}
    return _META


def _titleize(concept_id: str) -> str:
    slug = concept_id.split("__", 1)[-1].split("::")[-1]
    return slug.replace("_", " ").strip().title()


def _concept_name(cid: str, meta: Dict[str, Any]) -> str:
    info = meta["concepts"].get(cid)
    return info["name"] if info else _titleize(cid)


def _concept_chapter(cid: str, meta: Dict[str, Any]) -> str:
    info = meta["concepts"].get(cid)
    return info["chapter"] if info else ""


def _test_view(cs: Dict[str, Any]) -> Dict[str, Any]:
    """Part 12 quiz view for one concept: the mastery-gate state + the most recent
    TEST result (learner_state.record_test_result rows). Empty-safe."""
    hist = cs.get("test_history") or []
    gate = cs.get("mastery_gate", "none")
    view: Dict[str, Any] = {
        "tests_taken": len(hist),
        "mastery_gate": gate,
        **GATE_LABELS.get(gate, GATE_LABELS["none"]),
        "last_test": None,
    }
    if hist:
        last = hist[-1]
        n = int(last.get("n") or 0)
        view["last_test"] = {
            "date": (last.get("date") or "")[:10],
            "score_pct": round(float(last.get("score") or 0) * 100),
            "correct_of": f"{round(float(last.get('score') or 0) * n)} of {n}" if n else "",
            "n": n,
            "gate": last.get("gate", ""),
            "passed": last.get("gate") == "pass",
        }
    return view


def _mastery_status(mastery: float, measured: bool) -> Dict[str, str]:
    if not measured:
        return {"status": "started", "label": "Just started"}
    if mastery >= 0.70:
        return {"status": "strong", "label": "Doing well"}
    if mastery >= 0.45:
        return {"status": "growing", "label": "Getting there"}
    if mastery >= 0.30:
        return {"status": "learning", "label": "Still learning"}
    return {"status": "help", "label": "Needs practice"}


def _level_word(v: float) -> Dict[str, str]:
    if v >= 0.60:
        return {"level": "strong", "level_label": "Strong"}
    if v >= 0.40:
        return {"level": "ontrack", "level_label": "On track"}
    return {"level": "developing", "level_label": "Developing"}


def _tail_jsonl(path: Path, max_lines: int = 600) -> List[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").strip().splitlines()[-max_lines:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------
def build_progress_report(
    root: Optional[Path] = None,
    state_path: Optional[Path] = None,
    log_path: Optional[Path] = None,
    alerts_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """`root` supplies the store METADATA (concepts/graph — same in every store
    copy). state/log/alerts default to root's files but can be pointed at a
    fetched snapshot of the Jetson's files (parent_dashboard.py does this)."""
    root = Path(root) if root else ROOT
    meta = _load_meta(root)

    state_path = Path(state_path) if state_path else root / "learner_state.json"
    log_path = Path(log_path) if log_path else root / "rag_store" / "learning_log.jsonl"
    alerts_path = Path(alerts_path) if alerts_path else root / "rag_store" / "safety_alerts.jsonl"
    if not state_path.exists():
        return {"error": f"{state_path.name} not found", "generated_at": _now_iso()}
    state = json.loads(state_path.read_text(encoding="utf-8"))

    concept_states: Dict[str, dict] = state.get("concept_states") or {}
    session = state.get("session") or {}

    # --- topics (Class 10) and foundations (grade9 bridges) ----------------
    topics, foundations = [], []
    last_practiced_all: List[str] = []
    for cid, cs in concept_states.items():
        cs = cs or {}
        measured = "mastery" in cs
        mastery = float(cs.get("mastery", COLD_START_MASTERY))
        mastery = max(0.0, min(1.0, mastery))
        # Only flags still within their TTL are shown as CURRENT (audit A-6).
        # apply_deltas prunes on write, but it can only prune concepts the child
        # touched that turn — a topic left alone keeps its flags on disk until it
        # comes up again, and this dashboard is exactly where that reads as "your
        # child is confused about this", present tense. Filter on read too.
        flags = [
            {"flag": f, "since": (cs.get("flag_seen") or {}).get(f), **FLAG_LABELS[f]}
            for f in _live_flags(cs) if f in FLAG_LABELS
        ]
        struggling = bool((cs.get("struggle") or {}).get("struggling"))
        lp = cs.get("last_practiced")
        if lp:
            last_practiced_all.append(lp)
        entry = {
            "id": cid,
            "name": _concept_name(cid, meta),
            "chapter": _concept_chapter(cid, meta),
            "mastery_pct": round(mastery * 100),
            "measured": measured,
            **_mastery_status(mastery, measured),
            "flags": flags,
            "struggling": struggling,
            "last_practiced": lp,
            "test": _test_view(cs),   # Part 12 quiz/gate view
        }
        if cid.startswith("grade9::"):
            entry["chapter"] = "Class 9 foundation"
            foundations.append(entry)
        else:
            topics.append(entry)

    order = {"help": 0, "learning": 1, "growing": 2, "started": 3, "strong": 4}
    topics.sort(key=lambda t: (order.get(t["status"], 5), -len(t["flags"]), t["name"]))
    foundations.sort(key=lambda t: t["mastery_pct"])

    # --- trouble spots: tracked misconceptions + suspected flags -----------
    trouble = []
    for mid, ms in (state.get("misconception_states") or {}).items():
        node_id = mid if mid.startswith("misconception::") else f"misconception::{mid}"
        node = meta["mis_nodes"].get(node_id) or {}
        owner = meta["mis_owner"].get(node_id, "")
        status = (ms or {}).get("status", "active")
        trouble.append({
            "title": node.get("text") or _titleize(mid),
            "what_happened": node.get("why_wrong") or "",
            "correct_idea": node.get("correct_idea") or "",
            "concept_name": _concept_name(owner, meta) if owner else "",
            "status": status,
            **MISCONCEPTION_STATUS.get(status, MISCONCEPTION_STATUS["active"]),
            "last_probed": (ms or {}).get("last_probed"),
        })
    resolved_last = {"active": 0, "recurring": 1, "weakening": 2, "resolved": 3}
    trouble.sort(key=lambda t: resolved_last.get(t["status"], 0))

    suspected = [
        {"concept_name": t["name"], "chapter": t["chapter"]}
        for t in topics + foundations
        if any(f["flag"] == "misconception_suspected" for f in t["flags"])
    ]

    # --- thinking skills (HOPE rolling) -------------------------------------
    hope = state.get("hope_rolling") or {}
    thinking = []
    for key, info in THINKING_SKILLS.items():
        measured = key in hope
        v = float(hope.get(key, 0.5))
        thinking.append({
            "key": key, "label": info["label"], "help": info["help"],
            "value": round(v, 2), "pct": round(v * 100),
            "measured": measured,
            **(_level_word(v) if measured
               else {"level": "unmeasured", "level_label": "Not measured yet"}),
        })

    # --- mood from global EMA state -----------------------------------------
    g = state.get("global") or {}
    engagement = float(g.get("engagement", 0.5))
    confidence = float(g.get("confidence", 0.5))
    load = float(g.get("cognitive_load", 0.0))
    if load >= 0.6:
        mood = {"word": "Overloaded", "tone": "warn",
                "note": "Recent sessions felt heavy — shorter, easier sessions may help."}
    elif engagement >= 0.6 and confidence >= 0.55:
        mood = {"word": "Thriving", "tone": "good",
                "note": "Engaged and confident in recent sessions."}
    elif engagement >= 0.45:
        mood = {"word": "Steady", "tone": "good",
                "note": "Participating normally in recent sessions."}
    elif confidence < 0.35:
        mood = {"word": "Low confidence", "tone": "warn",
                "note": "Confidence has dipped — encouragement helps."}
    else:
        mood = {"word": "Quiet", "tone": "neutral",
                "note": "Less engaged lately — a fun topic may help restart."}
    mood["engagement_pct"] = round(engagement * 100)
    mood["confidence_pct"] = round(confidence * 100)

    # --- recent activity from the learning log ------------------------------
    days: Dict[str, dict] = {}
    for r in _tail_jsonl(log_path):
        ts = str(r.get("ts") or "")
        if len(ts) < 10:
            continue
        d = days.setdefault(ts[:10], {
            "date": ts[:10], "interactions": 0, "topics": [],
            "checks_passed": 0, "checks_partial": 0, "checks_missed": 0,
            "skill_checks": 0,
        })
        d["interactions"] += 1
        cid = ((r.get("concept") or {}).get("concept_id") or "")
        if cid and not cid.startswith("grade9::"):
            name = _concept_name(cid, meta)
            if name not in d["topics"]:
                d["topics"].append(name)
        wb = r.get("writeback") or {}
        outcome = wb.get("outcome")
        if outcome == "correct":
            d["checks_passed"] += 1
        elif outcome == "partial":
            d["checks_partial"] += 1
        elif outcome == "wrong":
            d["checks_missed"] += 1
        if r.get("hope_update"):
            d["skill_checks"] += 1
    recent = sorted(days.values(), key=lambda d: d["date"], reverse=True)[:14]

    # --- safety alerts (parents MUST see these) ------------------------------
    alerts = [
        {"ts": a.get("ts"), "message": a.get("utterance", ""),
         "handled": a.get("handled", "")}
        for a in _tail_jsonl(alerts_path, 50)
    ]
    alerts.reverse()  # latest first

    # --- quizzes: recent TEST results across all concepts (Part 12 §4.4) ------
    quizzes = []
    for cid, cs in concept_states.items():
        for row in ((cs or {}).get("test_history") or []):
            n = int(row.get("n") or 0)
            quizzes.append({
                "concept_name": _concept_name(cid, meta),
                "chapter": _concept_chapter(cid, meta),
                "date": (row.get("date") or "")[:10],
                "date_iso": row.get("date") or "",
                "score_pct": round(float(row.get("score") or 0) * 100),
                "correct_of": f"{round(float(row.get('score') or 0) * n)} of {n}" if n else "",
                "n": n,
                "gate": row.get("gate", ""),
                "passed": row.get("gate") == "pass",
            })
    quizzes.sort(key=lambda q: q["date_iso"], reverse=True)
    quizzes_taken = len(quizzes)
    quizzes_passed = sum(1 for q in quizzes if q["passed"])

    # --- header / summary -----------------------------------------------------
    current = session.get("current_concept") or ""
    class10 = [t for t in topics]
    strong = sum(1 for t in class10 if t["status"] == "strong")
    need_help = sum(
        1 for t in class10
        if t["status"] in ("help", "learning") or t["struggling"]
        or any(f["tone"] == "warn" for f in t["flags"])
    )
    overall = round(sum(t["mastery_pct"] for t in class10) / len(class10)) if class10 else 0
    last_active = max(last_practiced_all) if last_practiced_all else (
        recent[0]["date"] if recent else None)

    learner_id = state.get("learner_id") or "student"
    return {
        "generated_at": _now_iso(),
        "learner": {
            "id": learner_id,
            "name": learner_id.replace("_", " ").title(),
            "last_active": last_active,
            "current_topic": {
                "id": current,
                "name": _concept_name(current, meta) if current else "",
                "chapter": _concept_chapter(current, meta) if current else "",
            },
            "session_status": session.get("status", ""),
        },
        "summary": {
            "overall_mastery_pct": overall,
            "topics_total": len(class10),
            "topics_strong": strong,
            "topics_need_help": need_help,
            "foundations_to_revisit": sum(1 for f in foundations if f["mastery_pct"] < 60),
            "quizzes_taken": quizzes_taken,
            "quizzes_passed": quizzes_passed,
            "mood": mood,
        },
        "topics": topics,
        "foundations": foundations,
        "trouble_spots": trouble,
        "suspected_mixups": suspected,
        "thinking_skills": thinking,
        "quizzes": quizzes,
        "recent_activity": recent,
        "alerts": alerts,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    import sys
    out = build_progress_report()
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    print()
