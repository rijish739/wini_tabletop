"""Narrow normalization rules for learner-facing generated wording.

Only presentation-equivalent typography and whitespace are normalized.  Numbers,
word choice, ordering, and every non-answer field remain exact by design.
"""

from __future__ import annotations

import re
from typing import Any


WORDING_PATHS = frozenset({"result.answer", "compatibility.answer"})
_TYPOGRAPHY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def normalize_at_path(path: str, value: Any) -> Any:
    """Return the explicitly normalized comparison value for ``path``."""

    if path not in WORDING_PATHS or not isinstance(value, str):
        return value
    return re.sub(r"\s+", " ", value.translate(_TYPOGRAPHY)).strip()

