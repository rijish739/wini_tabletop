"""Crash-tolerant append-only cache for independently verified generated items."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .contracts import VerifiedItem

_LOCK = threading.Lock()


class VerifiedItemBank:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._items: dict[str, VerifiedItem] | None = None

    def load(self) -> dict[str, VerifiedItem]:
        if self._items is not None:
            return self._items
        items: dict[str, VerifiedItem] = {}
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    item = VerifiedItem.from_dict(row)
                    if item.item_verified and item.item_id and item.verification_token:
                        items[item.item_id] = item
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue  # tolerate a partial final line after a crash
        except FileNotFoundError:
            pass
        self._items = items
        return items

    def _append_verified(self, item: VerifiedItem) -> None:
        """Internal cache sink. Only items.verify() is allowed to call this."""
        if not item.item_verified or not item.verification_token:
            raise ValueError("only independently verified items may enter the bank")
        with _LOCK:
            current = self.load()
            if item.item_id in current:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            current[item.item_id] = item

    def select(self, concept_id: str, assessment_purpose: str,
               excluded_item_ids: set[str] | None = None) -> VerifiedItem | None:
        excluded = excluded_item_ids or set()
        matches = [item for item in self.load().values()
                   if item.concept_id == concept_id
                   and item.assessment_purpose == assessment_purpose
                   and item.item_id not in excluded]
        matches.sort(key=lambda item: (item.binary_item, item.item_id))
        return matches[0] if matches else None


def default_bank(root: Path | None = None) -> VerifiedItemBank:
    base = Path(root) if root is not None else Path(__file__).resolve().parent.parent / "rag_store"
    return VerifiedItemBank(base / "verified_items.jsonl")
