"""Clause-aware chunker for streaming speech (Part 13 Stage 1).

Streaming TTS is only as good as where you cut the text. The rules here exist so
that the FIRST chunk is short — that is what makes Wini start talking in ~1 s
instead of ~4 — while every later chunk stays long enough to carry natural
prosody. Cutting on every comma would start fast and then sound robotic; cutting
only on full stops keeps the first-audio latency tied to the first sentence's
length. So: break early once, then settle down.

Hard constraint (Part 13 §4 Stage 1.2): a chunk boundary must NEVER fall inside a
number or a maths phrase. Both rules below only break on punctuation followed by
whitespace, so "0.2" and "x squared" are structurally unsplittable — a decimal
point is never followed by a space, and maths phrases carry no internal
punctuation.

Feed it text as it streams; it yields only chunks it is SURE are complete.
"""

from __future__ import annotations

import re

# A terminator ends a sentence only when whitespace follows. This is the same
# rule _truncate_to_spoken_budget uses, and for the same reason: "20 / 0.2" must
# not split at the decimal point (2026-07-03 brick-wall transcript regression).
_SENT_END = re.compile(r"[.!?]+(?=\s)")
# Clause boundaries — used only past a length threshold, never as the default.
_CLAUSE = re.compile(r"[,;:](?=\s)|\s[—–]\s|\s--\s")

FIRST_MAX_CHARS = 60     # past this, the first chunk may break on a clause
MIN_CHARS = 25           # never emit a chunk shorter than this (except a flush)
LATER_MAX_CHARS = 140    # past this, a later chunk may also break on a clause


class ClauseChunker:
    """Incremental text -> speakable chunks.

    >>> c = ClauseChunker()
    >>> c.feed("The discriminant is b squared minus 4ac. ")
    ['The discriminant is b squared minus 4ac.']
    >>> c.feed("If D is 0.5, ")      # decimal must not split
    []
    >>> c.flush()
    'If D is 0.5,'
    """

    def __init__(self, first_max_chars: int = FIRST_MAX_CHARS,
                 min_chars: int = MIN_CHARS,
                 later_max_chars: int = LATER_MAX_CHARS) -> None:
        self._buf = ""
        self._n = 0                       # chunks emitted so far
        self.first_max_chars = first_max_chars
        self.min_chars = min_chars
        self.later_max_chars = later_max_chars

    # ------------------------------------------------------------------
    def _clause_budget(self) -> int:
        """How long the buffer must be before a clause break is allowed."""
        return self.first_max_chars if self._n == 0 else self.later_max_chars

    def _boundary(self) -> int | None:
        """Index just past the earliest legal break in the buffer, or None."""
        buf = self._buf
        # 1. A completed sentence is always a good break.
        m = _SENT_END.search(buf)
        if m and m.end() >= self.min_chars:
            return m.end()
        # 2. Otherwise a clause break, but only once the buffer is long enough
        #    that we are not chopping the line into fragments.
        if len(buf) >= self._clause_budget():
            for cm in _CLAUSE.finditer(buf):
                if cm.end() >= self.min_chars:
                    return cm.end()
        # 3. A very long run with no punctuation at all (rare) — break on a
        #    word boundary so one runaway sentence can't stall playback.
        if len(buf) >= self.later_max_chars * 2:
            sp = buf.rfind(" ", 0, self.later_max_chars)
            if sp >= self.min_chars:
                return sp
        return None

    # ------------------------------------------------------------------
    def feed(self, text: str) -> list[str]:
        """Add streamed text; return every chunk that is now complete."""
        if not text:
            return []
        self._buf += text
        out: list[str] = []
        while True:
            idx = self._boundary()
            if idx is None:
                break
            chunk = self._buf[:idx].strip()
            self._buf = self._buf[idx:].lstrip()
            if chunk:
                out.append(chunk)
                self._n += 1
        return out

    def flush(self) -> str:
        """The trailing remainder (call once the text stream has ended)."""
        tail = self._buf.strip()
        self._buf = ""
        if tail:
            self._n += 1
        return tail

    @property
    def chunks_emitted(self) -> int:
        return self._n


def chunk_text(text: str) -> list[str]:
    """Chunk a COMPLETE string (the non-streaming-generation path)."""
    c = ClauseChunker()
    out = c.feed(text)
    tail = c.flush()
    if tail:
        out.append(tail)
    return out


if __name__ == "__main__":
    samples = [
        "The discriminant tells you how many real roots a quadratic has. "
        "If it is positive there are two distinct roots, if it is zero the roots "
        "are equal, and if it is negative there are no real roots.",
        "Divide 20 by 0.2 to get 100. That is the area in square metres.",
        "Think of it like this: b squared minus 4ac is the deciding number, "
        "so once you know its sign you know the answer.",
    ]
    for s in samples:
        print(f"\n{s}")
        for i, c in enumerate(chunk_text(s)):
            print(f"  [{i}] ({len(c):3d}) {c}")
