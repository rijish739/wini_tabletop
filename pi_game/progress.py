"""Local SQLite progress store (§15 Progress Tracking, §16 Parent Dashboard).

Two rules from the spec shape the schema:

* **No scores, grades or ranking.** We record what happened — attempts, time,
  dates — never a judgement derived from it.
* **The child never sees any of this.** Nothing here is sent to the UI; only
  `parent_summary()` reads it back, for the parent dashboard.

One row per letter per completed lesson, so repeat visits accumulate rather than
overwrite (a child re-doing A is practice, not a correction).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "progress.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS lesson_run (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    letter          TEXT    NOT NULL,
    lang            TEXT    NOT NULL DEFAULT 'en',
    started_at      TEXT    NOT NULL,
    finished_at     TEXT,
    completed       INTEGER NOT NULL DEFAULT 0,
    touch_attempts  INTEGER NOT NULL DEFAULT 0,
    touch_correct   INTEGER NOT NULL DEFAULT 0,
    speech_attempts INTEGER NOT NULL DEFAULT 0,
    speech_matched  INTEGER NOT NULL DEFAULT 0,
    seconds         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_lesson_letter ON lesson_run(letter);
CREATE INDEX IF NOT EXISTS idx_lesson_day    ON lesson_run(started_at);
"""


def _conn(path: Path | None = None) -> sqlite3.Connection:
    c = sqlite3.connect(path or DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init(path: Path | None = None) -> None:
    with closing(_conn(path)) as c:
        c.executescript(SCHEMA)
        # Migrate a pre-Kannada database: the `lang` column was added when the
        # module learned a second alphabet. Existing rows are all English, which
        # is exactly the column default, so a plain ADD COLUMN backfills them.
        cols = {r["name"] for r in c.execute("PRAGMA table_info(lesson_run)")}
        if "lang" not in cols:
            c.execute("ALTER TABLE lesson_run ADD COLUMN lang TEXT NOT NULL DEFAULT 'en'")
        c.commit()


class Run:
    """One lesson attempt, from the intro to the completion screen."""

    def __init__(self, letter: str, lang: str = "en",
                 path: Path | None = None) -> None:
        self.path = path
        self.letter = letter
        self.lang = lang
        self.started = datetime.now()
        self.touch_attempts = 0
        self.touch_correct = 0
        self.speech_attempts = 0
        self.speech_matched = 0

    def save(self, completed: bool) -> None:
        secs = int((datetime.now() - self.started).total_seconds())
        with closing(_conn(self.path)) as c:
            c.execute(
                "INSERT INTO lesson_run (letter, lang, started_at, finished_at, completed,"
                " touch_attempts, touch_correct, speech_attempts, speech_matched, seconds)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (self.letter, self.lang, self.started.isoformat(timespec="seconds"),
                 datetime.now().isoformat(timespec="seconds"), int(completed),
                 self.touch_attempts, self.touch_correct,
                 self.speech_attempts, self.speech_matched, secs),
            )
            c.commit()


def completed_letters(lang: str | None = None, path: Path | None = None) -> list[str]:
    """Distinct completed letters, optionally scoped to one language.

    Scoping matters for resume: a child who finished English A has not met
    Kannada ಅ, and the two share nothing but a database.
    """
    sql = "SELECT DISTINCT letter FROM lesson_run WHERE completed=1"
    args: tuple = ()
    if lang is not None:
        sql += " AND lang=?"
        args = (lang,)
    sql += " ORDER BY letter"
    with closing(_conn(path)) as c:
        rows = c.execute(sql, args).fetchall()
    return [r["letter"] for r in rows]


def next_letter(order: list[str], lang: str | None = None,
                path: Path | None = None) -> str:
    """The first letter of `order` not yet completed; wraps to the start.

    Resume is deterministic (§12 "No random branching") — a child always picks up
    where the alphabet left off, and once every letter is done the module simply
    begins again rather than presenting a dead end.
    """
    done = set(completed_letters(lang, path))
    for ch in order:
        if ch not in done:
            return ch
    return order[0]


def parent_summary(path: Path | None = None) -> dict:
    """§16 — the only read path out of this store. Parents only, never the child."""
    with closing(_conn(path)) as c:
        agg = c.execute(
            "SELECT COUNT(*) runs, COALESCE(SUM(seconds),0) secs,"
            " COALESCE(SUM(speech_attempts),0) sa, COALESCE(SUM(speech_matched),0) sm,"
            " COALESCE(SUM(touch_attempts),0) ta, COALESCE(SUM(touch_correct),0) tc"
            " FROM lesson_run").fetchone()
        days = c.execute("SELECT COUNT(DISTINCT date(started_at)) d FROM lesson_run").fetchone()
        recent = c.execute(
            "SELECT letter, lang, date(started_at) day, touch_attempts, touch_correct,"
            " speech_attempts, speech_matched FROM lesson_run"
            " ORDER BY id DESC LIMIT 20").fetchall()
        by_lang = c.execute(
            "SELECT lang, COUNT(DISTINCT CASE WHEN completed=1 THEN letter END) done"
            " FROM lesson_run GROUP BY lang").fetchall()

    done = completed_letters(path=path)
    return {
        "letters_completed": done,
        "letters_completed_count": len(done),
        "practice_seconds": agg["secs"],
        "days_practiced": days["d"],
        "speech_attempts": agg["sa"],
        "speech_matched": agg["sm"],
        "touch_attempts": agg["ta"],
        "touch_correct": agg["tc"],
        # "Confidence trend" in §16 terms: the share of attempts that landed,
        # reported as a trend for parents — never surfaced to the child, and
        # deliberately not a score or a grade.
        "touch_confidence": round(agg["tc"] / agg["ta"], 3) if agg["ta"] else None,
        "speech_confidence": round(agg["sm"] / agg["sa"], 3) if agg["sa"] else None,
        "lesson_runs": agg["runs"],
        "letters_completed_by_lang": {r["lang"]: r["done"] for r in by_lang},
        "today": date.today().isoformat(),
        "recent": [dict(r) for r in recent],
    }
