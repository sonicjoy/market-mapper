"""Polymarket team labels from Unmapped Why titles."""

from __future__ import annotations

import re
from typing import Any

from mappers.handicap_name_crumb import is_selection_alias

_VS = re.compile(r"\s+vs\.?\s+", re.I)
_POLY_WIN = re.compile(r"^will\s+(.+?)\s+win\b", re.I)
POLY_YES_NO = frozenset({"yes", "no", "yes.", "no."})
_POLY_MARKET_TAILS = (
    "both teams",
    "btts",
    "map 1",
    "map 2",
    "winner",
    "total",
    "spread",
    "handicap",
    "corners",
    "second half",
    "first half",
    "to score",
    "over/under",
    "o/u",
    "exact score",
    "correct score",
    "completed match",
)


def _strip_poly_market_tail(label: str) -> str:
    """Drop trailing Poly market titles glued onto a team after ':' or '-'."""
    text = label.strip()
    for sep in (": ", " - ", " – "):
        if sep not in text:
            continue
        left, right = text.rsplit(sep, 1)
        blob = right.casefold()
        if any(hint in blob for hint in _POLY_MARKET_TAILS):
            return left.strip()
    return text


def poly_team_labels(row: dict[str, Any]) -> list[str]:
    """Team names from a Poly question; never the market title after vs."""
    desc = str(row.get("platform_leg_description") or "")
    question = desc.split(" — ", 1)[0].strip() if " — " in desc else desc
    outcome = desc.split(" — ", 1)[1].strip() if " — " in desc else ""
    fixture = str(row.get("fixture") or question)
    matched = _POLY_WIN.match(question) or _POLY_WIN.match(fixture.strip())
    if matched:
        return _entity_labels([matched.group(1).strip()])
    if outcome and not is_selection_alias(outcome):
        return _entity_labels([outcome])
    if _VS.search(fixture):
        labels: list[str] = []
        for part in _VS.split(fixture, maxsplit=1):
            label = _strip_poly_market_tail(part)
            if label:
                labels.append(label)
        return _entity_labels(labels)
    return []


def _entity_labels(labels: list[str]) -> list[str]:
    """Drop Yes/No, O/U, and other selection crumbs."""
    return [label for label in labels if label and not is_selection_alias(label)]
