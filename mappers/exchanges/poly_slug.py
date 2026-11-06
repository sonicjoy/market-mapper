"""Official Polymarket dated slugs (``bun-stu-koe-2026-09-04-exact-score-0-0``)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_HYPHEN_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+", re.I)
_SKIP_PREFIX = frozenset(
    {
        "a",
        "an",
        "and",
        "do",
        "for",
        "how",
        "is",
        "it",
        "map",
        "the",
        "this",
        "that",
        "to",
        "we",
        "why",
        "you",
        "yes",
        "not",
    }
)


@dataclass(frozen=True)
class PolySlug:
    """``{prefix}-{home}-{away}-{date}-{suffix}`` from an official Path 2 slug."""

    prefix: str
    home: str
    away: str
    date: str
    suffix: str
    raw: str


# legacy: ticker parse — replace with the typed venue field, do not extend
def parse_poly_slug(ticker: str) -> PolySlug | None:
    """Split an official dated slug; None when the shape does not fit."""
    text = (ticker or "").strip().lower()
    if not text or any(ch.isspace() for ch in text):
        return None
    found = _DATE.search(text)
    if found is None:
        return None
    parts = text[: found.start()].rstrip("-").split("-")
    if len(parts) < 3 or parts[0] in _SKIP_PREFIX:
        return None
    return PolySlug(
        prefix=parts[0],
        home=parts[1],
        away=parts[-1],
        date=found.group(1),
        suffix=text[found.end() :].lstrip("-"),
        raw=text,
    )


def find_poly_slug(text: str) -> str:
    """First official Polymarket dated slug in ``text``, if any."""
    stripped = (text or "").strip()
    parsed = parse_poly_slug(stripped)
    if parsed is not None:
        return parsed.raw
    for tok in _HYPHEN_ID.findall(stripped):
        parsed = parse_poly_slug(tok)
        if parsed is not None:
            return parsed.raw
    return ""


def slug_gap_kind(suffix: str) -> str:
    """Unmapped Why shape for a slug suffix; default is a generic miss."""
    blob = (suffix or "").replace("_", "-").casefold()
    if "exact-score" in blob or "exactscore" in blob:
        return "exact_score"
    return "unmapped"
