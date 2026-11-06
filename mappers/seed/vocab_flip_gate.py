"""Gate a Python vocab-dict delete on a complete tip.

Legacy: the tip is retiring and Python vocab is the home for rules; do not
delete vocab dicts in favour of the tip.

Do not delete the file when this returns any key. Keep the file one tick
past Approve so the mapper still has the dict if the new tip is rolled back.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


def missing_vocab_keys(
    file_keys: Iterable[str],
    rules: Sequence[Any],
    *,
    sportsbook: str,
    source_key_type: str,
    league: str | None = None,
) -> list[str]:
    """File keys the tip does not map or ignore for this book and key type."""
    covered = {
        str(getattr(row, "source_key", "") or "")
        for row in rules
        if _covers(row, sportsbook=sportsbook, source_key_type=source_key_type, league=league)
    }
    return sorted(key for key in file_keys if key not in covered)


def _covers(
    row: Any,
    *,
    sportsbook: str,
    source_key_type: str,
    league: str | None,
) -> bool:
    if getattr(row, "tombstone", False) or not getattr(row, "enabled", True):
        return False
    if str(getattr(row, "sportsbook", "") or "") != sportsbook:
        return False
    if str(getattr(row, "source_key_type", "") or "") != source_key_type:
        return False
    if str(getattr(row, "action", "") or "") not in {"map", "ignore"}:
        return False
    if league is not None and str(getattr(row, "league", "") or "") != league:
        return False
    return bool(str(getattr(row, "source_key", "") or ""))
